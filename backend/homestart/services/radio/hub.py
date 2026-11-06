"""Relays internet radio streams to the browsers.

There is one connection to a station however many listeners it has; it is closed when the last one leaves.
Source addresses come only from the database (set by an administrator), never from a request.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx

from .icy import IcyDemuxer

log = logging.getLogger("homestart.radio")

CONNECT_TIMEOUT = 10.0
# A source that sends nothing for this long is treated as dropped.
STALL_TIMEOUT = 15.0
MAX_REDIRECTS = 5
MAX_RECONNECTS = 3
RECONNECT_DELAY = 1.0
# A connection that lasted this long counts as healthy, so the reconnect counter starts again.
HEALTHY_AFTER = 30.0
LISTENER_QUEUE_CHUNKS = 64
DEFAULT_CONTENT_TYPE = "audio/mpeg"


class RadioError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class StationSpec:
    slug: str
    urls: tuple[str, ...]
    content_type: str | None = None


@dataclass
class Listener:
    stream: "Stream"
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(LISTENER_QUEUE_CHUNKS))
    closed: bool = False

    async def chunks(self):
        try:
            while True:
                item = await self.queue.get()
                if item is None:
                    return
                yield item
        finally:
            self.close()

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.stream.remove(self)

    def push(self, chunk: bytes | None) -> None:
        if self.queue.full():
            # A slow listener loses the oldest audio instead of holding the others back.
            self.queue.get_nowait()
        self.queue.put_nowait(chunk)


class Stream:
    """The one upstream connection of a station and the listeners that share it."""

    def __init__(self, hub: "RadioHub", spec: StationSpec):
        self.hub = hub
        self.spec = spec
        self.listeners: list[Listener] = []
        self.title: str | None = None
        self.content_type: str = spec.content_type or DEFAULT_CONTENT_TYPE
        self.closed = False
        self.ready: asyncio.Future = asyncio.get_running_loop().create_future()
        self.task = asyncio.create_task(self._run())

    def add_listener(self) -> Listener:
        listener = Listener(self)
        self.listeners.append(listener)
        return listener

    def remove(self, listener: Listener) -> None:
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            self.shutdown()

    def shutdown(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.hub.streams.pop(self.spec.slug, None)
        self.task.cancel()

    def _broadcast(self, chunk: bytes | None) -> None:
        for listener in list(self.listeners):
            listener.push(chunk)

    async def _open(self, client: httpx.AsyncClient):
        """Tries the source addresses in order and returns the first response that carries audio."""
        last_error = "no source address"
        for url in self.spec.urls:
            try:
                request = client.build_request("GET", url, headers={"Icy-MetaData": "1", "Accept": "*/*"})
                response = await asyncio.wait_for(client.send(request, stream=True), CONNECT_TIMEOUT + 2)
            except (httpx.HTTPError, asyncio.TimeoutError) as exc:
                last_error = f"{type(exc).__name__}"
                log.warning("Station %s: %s did not answer (%s)", self.spec.slug, url, last_error)
                continue
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if response.status_code != 200 or content_type.startswith(("text/", "image/")):
                await response.aclose()
                last_error = f"HTTP {response.status_code} {content_type}".strip()
                log.warning("Station %s: %s is not usable (%s)", self.spec.slug, url, last_error)
                continue
            return response
        raise RadioError(502, f"The station did not answer ({last_error})")

    async def _run(self) -> None:
        reconnects = 0
        first = True
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(CONNECT_TIMEOUT, read=STALL_TIMEOUT),
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                # IPv4 only: httpx tries IPv6 first and waits about 5 s for it on networks without IPv6.
                transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0"),
            ) as client:
                while True:
                    started = time.monotonic()
                    try:
                        response = await self._open(client)
                    except RadioError as exc:
                        if first:
                            self._fail_start(exc)
                            return
                        reconnects += 1
                        if reconnects > MAX_RECONNECTS:
                            self._broadcast(None)
                            return
                        await asyncio.sleep(RECONNECT_DELAY)
                        continue
                    try:
                        if first:
                            first = False
                            if self.spec.content_type is None:
                                header = response.headers.get("content-type", "").split(";")[0].strip()
                                self.content_type = header or DEFAULT_CONTENT_TYPE
                            if not self.ready.done():
                                self.ready.set_result(None)
                        await self._pump(response)
                    finally:
                        await response.aclose()
                    if time.monotonic() - started > HEALTHY_AFTER:
                        reconnects = 0
                    reconnects += 1
                    if reconnects > MAX_RECONNECTS:
                        log.warning("Station %s: the source keeps dropping, closing", self.spec.slug)
                        self._broadcast(None)
                        return
                    await asyncio.sleep(RECONNECT_DELAY)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a relay must never take the application down
            log.exception("Station %s: relay failed", self.spec.slug)
            if not self.ready.done():
                self._fail_start(RadioError(502, "The station could not be opened"))
            else:
                self._broadcast(None)
        finally:
            if not self.closed:
                self.closed = True
                self.hub.streams.pop(self.spec.slug, None)

    def _fail_start(self, error: RadioError) -> None:
        if not self.ready.done():
            self.ready.set_exception(error)
            # Nobody may be waiting any more; the exception must not be reported as never retrieved.
            self.ready.exception()
        self._broadcast(None)

    async def _pump(self, response: httpx.Response) -> None:
        demuxer = None
        try:
            metaint = int(response.headers.get("icy-metaint", "0"))
        except ValueError:
            metaint = 0
        if metaint > 0:
            demuxer = IcyDemuxer(metaint)
        iterator = response.aiter_raw()
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(iterator.__anext__(), STALL_TIMEOUT)
                except StopAsyncIteration:
                    return
                except (asyncio.TimeoutError, httpx.HTTPError):
                    return
                if demuxer is not None:
                    chunk = demuxer.feed(chunk)
                    self.title = demuxer.title
                if chunk:
                    self._broadcast(chunk)
        finally:
            await iterator.aclose()


class RadioHub:
    def __init__(self, max_listeners: int):
        self.max_listeners = max_listeners
        self.streams: dict[str, Stream] = {}
        self.started_at = time.time()

    def listener_count(self) -> int:
        return sum(len(stream.listeners) for stream in self.streams.values())

    def stream_info(self, slug: str) -> tuple[int, str | None]:
        stream = self.streams.get(slug)
        return (len(stream.listeners), stream.title) if stream else (0, None)

    async def subscribe(self, spec: StationSpec) -> tuple[Listener, str]:
        """Joins (or starts) the relay of a station. Raises RadioError(503/502)."""
        if self.listener_count() >= self.max_listeners:
            raise RadioError(503, "Too many listeners")
        stream = self.streams.get(spec.slug)
        if stream is None or stream.closed:
            stream = Stream(self, spec)
            self.streams[spec.slug] = stream
        # The slot is taken before waiting for the station, so parallel requests cannot exceed the limit.
        listener = stream.add_listener()
        try:
            await asyncio.shield(stream.ready)
        except BaseException:
            listener.close()
            raise
        return listener, stream.content_type

    async def stop(self) -> None:
        for stream in list(self.streams.values()):
            stream.shutdown()
            stream._broadcast(None)

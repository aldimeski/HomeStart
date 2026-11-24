"""Listening sessions: the queue and the state of each listener, and the count of streams."""

import asyncio
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

REPEAT_MODES = ("off", "all", "one")
SESSION_IDLE_SECONDS = 6 * 3600
MAX_SESSIONS = 100
MAX_QUEUE = 5000
# Tracks that fail one after the other before playback stops, so a broken location does not loop forever.
MAX_CONSECUTIVE_ERRORS = 3
# One session streams the current track and the one loaded ahead; a seek may briefly add a connection.
MAX_STREAMS_PER_SESSION = 4


class HubFull(Exception):
    """Too many listeners at the same time."""


@dataclass
class Session:
    key: str
    queue: list[int] = field(default_factory=list)  # track ids in the order they are played
    base: list[int] = field(default_factory=list)  # the same ids in the order they were added (for shuffle off)
    index: int = 0
    status: Literal["stopped", "playing", "paused"] = "stopped"
    shuffle: bool = False
    repeat: Literal["off", "all", "one"] = "off"
    errors: int = 0
    version: int = 0
    touched: float = field(default_factory=time.monotonic)
    waiters: set = field(default_factory=set)

    @property
    def current_id(self) -> int | None:
        return self.queue[self.index] if 0 <= self.index < len(self.queue) else None

    @property
    def next_id(self) -> int | None:
        """The track after the current one, as playback will reach it; None when playback ends there or repeats one."""
        if not self.queue or self.repeat == "one":
            return None
        if self.index + 1 < len(self.queue):
            return self.queue[self.index + 1]
        return self.queue[0] if self.repeat == "all" and len(self.queue) > 1 else None

    # --- queue changes ---------------------------------------------------------

    def play(self, ids: list[int], start_id: int | None = None) -> None:
        ids = ids[:MAX_QUEUE]
        self.base = list(ids)
        start = ids.index(start_id) if start_id in ids else None
        if self.shuffle:
            rest = [i for n, i in enumerate(ids) if n != start]
            random.shuffle(rest)
            self.queue = ([ids[start]] if start is not None else []) + rest
            self.index = 0
        else:
            self.queue = list(ids)
            self.index = start or 0
        self.status = "playing"
        self.errors = 0

    def enqueue(self, ids: list[int]) -> None:
        room = MAX_QUEUE - len(self.queue)
        self.queue += ids[:room]
        self.base += ids[:room]

    def play_next(self, ids: list[int]) -> None:
        room = MAX_QUEUE - len(self.queue)
        ids = ids[:room]
        self.queue[self.index + 1 : self.index + 1] = ids
        self.base += ids

    def set_shuffle(self, on: bool) -> None:
        if on == self.shuffle:
            return
        self.shuffle = on
        current = self.current_id
        if not self.queue:
            return
        if on:
            rest = self.queue[self.index + 1 :]
            random.shuffle(rest)
            self.queue = self.queue[: self.index + 1] + rest
        else:
            present = set(self.queue)
            self.queue = [i for i in self.base if i in present]
            self.index = self.queue.index(current) if current in self.queue else 0

    def advance(self, step: int) -> None:
        """Moves to the next (step 1) or previous (step -1) track; the end of the queue stops playback."""
        target = self.index + step
        if 0 <= target < len(self.queue):
            self.index = target
        elif self.repeat == "all" and self.queue:
            self.index = 0 if step > 0 else len(self.queue) - 1
        elif step > 0:
            self.index, self.status = 0, "stopped"

    def on_error(self) -> None:
        self.errors += 1
        if self.errors >= MAX_CONSECUTIVE_ERRORS:
            self.status = "stopped"
            self.errors = 0
        else:
            self.advance(1)

    def remove_ids(self, gone: set[int]) -> None:
        """Takes tracks that left the library out of the queue."""
        if not gone & set(self.queue):
            return
        before = sum(1 for i in self.queue[: self.index] if i in gone)
        self.queue = [i for i in self.queue if i not in gone]
        self.base = [i for i in self.base if i not in gone]
        self.index = max(0, min(self.index - before, len(self.queue) - 1))
        if not self.queue:
            self.status, self.index = "stopped", 0

    def clear(self) -> None:
        self.queue, self.base, self.index, self.status, self.errors = [], [], 0, "stopped", 0


class PlayerHub:
    def __init__(self, max_listeners: int):
        self.max_listeners = max_listeners
        self._lock = threading.RLock()
        self._sessions: dict[str, Session] = {}
        self._streams: dict[str, int] = {}

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def session(self, key: str) -> Session:
        with self._lock:
            now = time.monotonic()
            for old in [k for k, s in self._sessions.items() if now - s.touched > SESSION_IDLE_SECONDS and k not in self._streams]:
                del self._sessions[old]
            session = self._sessions.get(key)
            if session is None:
                if len(self._sessions) >= MAX_SESSIONS:
                    raise HubFull
                session = self._sessions[key] = Session(key=key)
            session.touched = now
            return session

    def changed(self, session: Session) -> None:
        """Bumps the version and wakes everybody waiting for news of this session (called from any thread)."""
        with self._lock:
            session.version += 1
            waiters, session.waiters = session.waiters, set()
        for future in waiters:
            future.get_loop().call_soon_threadsafe(lambda f=future: f.done() or f.set_result(None))

    async def wait_for_change(self, session: Session, version: int, timeout: float) -> bool:
        """True when the session changed after the given version, False when the time ran out."""
        with self._lock:
            if session.version != version:
                return True
            future = asyncio.get_running_loop().create_future()
            session.waiters.add(future)
        try:
            await asyncio.wait_for(asyncio.shield(future), timeout)
            return True
        except TimeoutError:
            return False
        finally:
            with self._lock:
                session.waiters.discard(future)

    def acquire_stream(self, key: str) -> Callable[[], None]:
        """Counts a stream for the session; raises HubFull when the listener limit is reached. Returns the release."""
        with self._lock:
            if key not in self._streams and len(self._streams) >= self.max_listeners:
                raise HubFull
            if self._streams.get(key, 0) >= MAX_STREAMS_PER_SESSION:
                raise HubFull
            self._streams[key] = self._streams.get(key, 0) + 1
        released = False

        def release() -> None:
            nonlocal released
            with self._lock:
                if released:
                    return
                released = True
                remaining = self._streams.get(key, 1) - 1
                if remaining <= 0:
                    self._streams.pop(key, None)
                else:
                    self._streams[key] = remaining

        return release

    def listeners(self) -> int:
        with self._lock:
            return len(self._streams)

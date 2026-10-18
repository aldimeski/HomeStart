"""Keeps a permanent connection to the MQTT broker and reconnects when it drops."""

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable

import aiomqtt

log = logging.getLogger("homestart.mqtt")

SUBSCRIPTIONS = (
    # All tele topics (not only LWT/STATE/SENSOR), so a console without HTTP access still shows INFO, RESULT …
    "tele/+/+",
    "stat/+/+",
    "tasmota/discovery/+/config",
    "tasmota/discovery/+/sensors",
)
RECONNECT_MIN_SECONDS = 2
RECONNECT_MAX_SECONDS = 60

MessageHandler = Callable[[str, bytes, bool], None]
ConnectionHandler = Callable[[bool], Awaitable[None]]


class MqttUnavailable(Exception):
    pass


class MqttLink:
    def __init__(self, host: str, port: int, on_message: MessageHandler, on_connection: ConnectionHandler):
        self.host = host
        self.port = port
        self._on_message = on_message
        self._on_connection = on_connection
        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task | None = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="homestart-mqtt")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def publish(self, topic: str, payload: str = "") -> None:
        if self._client is None:
            raise MqttUnavailable("MQTT broker is not connected")
        try:
            await self._client.publish(topic, payload)
        except aiomqtt.MqttError as exc:
            raise MqttUnavailable(str(exc)) from exc

    async def _run(self) -> None:
        delay = RECONNECT_MIN_SECONDS
        while True:
            try:
                async with aiomqtt.Client(
                    self.host, self.port, identifier=f"homestart-{secrets.token_hex(4)}", keepalive=30
                ) as client:
                    for topic in SUBSCRIPTIONS:
                        await client.subscribe(topic)
                    self._client = client
                    delay = RECONNECT_MIN_SECONDS
                    log.info("Connected to MQTT broker %s:%s", self.host, self.port)
                    await self._on_connection(True)
                    async for message in client.messages:
                        try:
                            payload = message.payload
                            if not isinstance(payload, (bytes, bytearray)):
                                payload = b"" if payload is None else str(payload).encode()
                            self._on_message(str(message.topic), bytes(payload), message.retain)
                        except Exception:
                            log.exception("Failed to handle MQTT message on %s", message.topic)
            except aiomqtt.MqttError as exc:
                log.warning("MQTT broker %s:%s unavailable (%s); retrying in %ss", self.host, self.port, exc, delay)
            finally:
                if self._client is not None:
                    self._client = None
                    await self._on_connection(False)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_SECONDS)

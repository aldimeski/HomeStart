"""Live device consoles: the Tasmota web log read over HTTP, and commands sent over MQTT.

One poller runs per device while at least one browser watches it, however many browsers do.
Without HTTP access (no stored login, or the web interface does not answer) the console shows
the device's MQTT messages instead, which are also the main lines of the Tasmota log.
"""

import asyncio
import json
import logging
import re
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING, Any

import httpx

from . import http_api
from .http_api import AuthRequired, DeviceUnreachable
from .mqtt_link import MqttUnavailable

if TYPE_CHECKING:
    from .manager import TasmotaManager

log = logging.getLogger("homestart.tasmota")

POLL_INTERVAL_SECONDS = 1.0
HTTP_RETRY_SECONDS = 15.0
HISTORY_LINES = 300
MAX_LINE_LENGTH = 4000
MAX_COMMAND_LENGTH = 255
LISTENER_QUEUE_SIZE = 1000
# The command word becomes part of the MQTT topic, so wildcards and separators must not get in.
COMMAND_WORD = re.compile(r"^[A-Za-z0-9_]{1,64}$")
POWER_WORD = re.compile(r"^POWER(\d*)$", re.IGNORECASE)

SOURCE_HTTP = "http"
SOURCE_MQTT = "mqtt"


class DeviceConsole:
    def __init__(self, manager: "TasmotaManager", device_id: int):
        self.manager = manager
        self.device_id = device_id
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY_LINES)
        self.source = SOURCE_MQTT
        self.notice: str | None = "Connecting to the device…"
        self._listeners: set[asyncio.Queue] = set()
        self._next_id = 1
        self._task: asyncio.Task | None = None

    # --- listeners -------------------------------------------------------------------

    def attach(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=LISTENER_QUEUE_SIZE)
        self._listeners.add(queue)
        if self._task is None:
            self._task = asyncio.create_task(self._poll(), name=f"homestart-console-{self.device_id}")
        return queue

    def detach(self, queue: asyncio.Queue) -> bool:
        """Returns True when nobody watches any more and the console was stopped."""
        self._listeners.discard(queue)
        if self._listeners:
            return False
        self.stop()
        return True

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    def status(self) -> dict[str, Any]:
        return {"type": "source", "source": self.source, "notice": self.notice}

    def _broadcast(self, message: dict[str, Any]) -> None:
        for queue in list(self._listeners):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # A browser that fell behind gets the recent history again instead of the backlog.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({"type": "reset", "lines": list(self.history)})

    def add_lines(self, kind: str, texts: list[str]) -> None:
        lines = []
        for text in texts:
            line = {"id": self._next_id, "kind": kind, "text": text[:MAX_LINE_LENGTH]}
            self._next_id += 1
            self.history.append(line)
            lines.append(line)
        if lines:
            self._broadcast({"type": "lines", "lines": lines})

    def _set_source(self, source: str, notice: str | None) -> None:
        if (source, notice) != (self.source, self.notice):
            self.source, self.notice = source, notice
            self._broadcast(self.status())

    # --- log sources -----------------------------------------------------------------

    async def _poll(self) -> None:
        index = 0
        async with httpx.AsyncClient(timeout=http_api.HTTP_TIMEOUT) as client:
            while True:
                device = self.manager.devices.get(self.device_id)
                if device is None or device.removed:
                    return
                if not device.host:
                    self._set_source(SOURCE_MQTT, "The device address is unknown; only MQTT messages are shown.")
                    await asyncio.sleep(HTTP_RETRY_SECONDS)
                    continue

                credentials = self.manager.credentials()
                try:
                    index, lines = await http_api.console_log(device.host, device.port, index, credentials, client)
                except AuthRequired:
                    if credentials:
                        notice = "The stored Tasmota login was not accepted; only MQTT messages are shown."
                    else:
                        notice = (
                            "The device requires a login. Set the shared Tasmota credentials in "
                            "Configuration → Devices to see the full log; until then only MQTT messages are shown."
                        )
                    self._set_source(SOURCE_MQTT, notice)
                    await asyncio.sleep(HTTP_RETRY_SECONDS)
                    continue
                except DeviceUnreachable:
                    self._set_source(SOURCE_MQTT, "The web interface does not respond; only MQTT messages are shown.")
                    await asyncio.sleep(HTTP_RETRY_SECONDS)
                    continue

                self._set_source(SOURCE_HTTP, None)
                self.add_lines("log", lines)
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

    def mqtt_message(self, topic: str, payload: bytes, retained: bool) -> None:
        # With the HTTP log the device already reports these lines itself; retained ones are old.
        if self.source == SOURCE_HTTP or retained:
            return
        text = payload.decode(errors="replace")
        self.add_lines("log", [f"{datetime.now():%H:%M:%S} MQT: {topic} = {text}"])

    # --- commands ---

    @staticmethod
    def _switches_locked_relay(word: str, payload: str, locked: set[int]) -> bool:
        """Power commands (also inside Backlog) must respect switch locks; a bare "Power1" only reads the state."""
        if not locked:
            return False
        if word.upper() == "BACKLOG":
            for part in payload.split(";"):
                inner_word, _, inner_payload = part.strip().partition(" ")
                if DeviceConsole._switches_locked_relay(inner_word, inner_payload, locked):
                    return True
            return False
        match = POWER_WORD.match(word)
        if not match or not payload.strip():
            return False
        channel = int(match.group(1) or 1)
        return channel == 0 or channel in locked  # Power0 switches all relays-----------------------------------------------------------------

    async def command(self, text: str, username: str) -> None:
        text = text.strip()
        if not text:
            return
        if len(text) > MAX_COMMAND_LENGTH or "\n" in text or "\r" in text:
            self.add_lines("error", [f"Commands are limited to one line of {MAX_COMMAND_LENGTH} characters."])
            return
        word, _, payload = text.partition(" ")
        if not COMMAND_WORD.match(word):
            self.add_lines("error", [f"Not a Tasmota command: {word}"])
            return

        from .manager import LOCKED_MESSAGE, DeviceError  # manager imports this module

        device = self.manager.devices.get(self.device_id)
        if device is None or device.removed:
            self.add_lines("error", ["The device was removed."])
            return
        if self._switches_locked_relay(word, payload, self.manager.locked_channels(device)):
            self.add_lines("command", [text])
            self.add_lines("error", [f"{LOCKED_MESSAGE}; unlock it on the device card first."])
            return

        self.add_lines("command", [text])
        # Only the command word is logged; commands such as WebPassword or Password1 carry secrets.
        log.info("Console command %s sent to %s by %s", word, device.mqtt_topic or device.host, username)
        try:
            if self.manager.uses_mqtt(device):
                await self.manager.publish(f"cmnd/{device.mqtt_topic}/{word}", payload.strip())
            else:
                result = await self.manager.http_command(device, text)
                if self.source != SOURCE_HTTP:
                    self.add_lines("log", [f"{datetime.now():%H:%M:%S} RESULT = {json.dumps(result)}"])
        except MqttUnavailable:
            self.add_lines("error", ["The MQTT broker is not connected."])
        except DeviceError as exc:
            self.add_lines("error", [str(exc)])

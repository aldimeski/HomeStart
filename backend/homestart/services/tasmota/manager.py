"""Device registry for TasmoSiz: discovery, live state, commands and change notifications.

Static device data (topic, IP, MAC, firmware, names) is stored in the database; live data
(relays, sensors, WiFi, online) is kept in memory and rebuilt from MQTT after a restart.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select

from ...config import Settings
from ...db import SessionLocal
from ...models import AppSetting, TasmotaDevice, utcnow
from ..secret_box import SecretBox
from . import http_api
from .console import DeviceConsole
from .http_api import AuthRequired, Credentials, DeviceUnreachable
from .mqtt_link import MqttLink, MqttUnavailable
from .parsing import (
    Update,
    clean_relay_names,
    decode_json,
    normalize_mac,
    parse_discovery_config,
    parse_discovery_sensors,
    parse_power_message,
    parse_result,
    parse_sensor,
    parse_state,
    parse_status,
    sensor_readings,
)

log = logging.getLogger("homestart.tasmota")

POWER_TIMEOUT_SECONDS = 4.0
STATUS_QUERY_SPACING_SECONDS = 0.15
NOTIFY_DELAY_SECONDS = 0.15
LAST_SEEN_WRITE_INTERVAL = timedelta(minutes=5)
LISTENER_QUEUE_SIZE = 500

CREDENTIAL_USER_KEY = "tasmota_username"
CREDENTIAL_PASSWORD_KEY = "tasmota_password"


class DeviceError(Exception):
    """A problem the user should see, e.g. an offline or unreachable device."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class LiveState:
    online: bool | None = None
    power: dict[int, str] = field(default_factory=dict)
    sensors: dict[str, Any] | None = None
    wifi: dict[str, int] | None = None
    uptime: str | None = None
    relay_count: int | None = None


class TasmotaManager:
    def __init__(self, settings: Settings, secret_box: SecretBox):
        self.settings = settings
        self.box = secret_box
        self.devices: dict[int, TasmotaDevice] = {}
        self.live: dict[int, LiveState] = {}
        self.by_topic: dict[str, int] = {}
        self.mqtt: MqttLink | None = None
        if settings.mqtt_enabled:
            self.mqtt = MqttLink(settings.mqtt_host, settings.mqtt_port, self.handle_message, self._on_connection)

        self._listeners: set[asyncio.Queue] = set()
        self._dirty: set[int] = set()
        self._notify_scheduled = False
        self._power_waiters: dict[str, list[tuple[int, asyncio.Future]]] = {}
        self._queried_topics: set[str] = set()
        self._query_queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        self.consoles: dict[int, DeviceConsole] = {}

    # --- lifecycle ---------------------------------------------------------------

    def load(self) -> None:
        with SessionLocal() as db:
            for device in db.scalars(select(TasmotaDevice)).all():
                self._register(device)

    async def start(self) -> None:
        self.load()
        if self.mqtt:
            self.mqtt.start()
            self._tasks.append(asyncio.create_task(self._status_query_worker(), name="homestart-status-queries"))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for console in self.consoles.values():
            console.stop()
        if self.mqtt:
            await self.mqtt.stop()

    @property
    def mqtt_connected(self) -> bool:
        return bool(self.mqtt and self.mqtt.connected)

    async def _on_connection(self, connected: bool) -> None:
        self._broadcast({"type": "mqtt", "connected": connected})
        if connected:
            # STATE is otherwise only published every TelePeriod, so ask every known device right away.
            try:
                for device in list(self.devices.values()):
                    if device.mqtt_topic and not device.removed:
                        await self.publish(f"cmnd/{device.mqtt_topic}/STATE")
            except MqttUnavailable as exc:
                log.warning("Could not query device state: %s", exc)

    async def _status_query_worker(self) -> None:
        while True:
            topic = await self._query_queue.get()
            try:
                await self.publish(f"cmnd/{topic}/Status", "0")
            except MqttUnavailable:
                self._queried_topics.discard(topic)
            await asyncio.sleep(STATUS_QUERY_SPACING_SECONDS)

    async def publish(self, topic: str, payload: str = "") -> None:
        if not self.mqtt:
            raise MqttUnavailable("MQTT is disabled")
        await self.mqtt.publish(topic, payload)

    def _query_status(self, topic: str) -> None:
        if topic not in self._queried_topics:
            self._queried_topics.add(topic)
            self._query_queue.put_nowait(topic)

    # --- registry and persistence -----------------------------------------------

    def _register(self, device: TasmotaDevice) -> None:
        self.devices[device.id] = device
        self.live.setdefault(device.id, LiveState())
        if device.mqtt_topic:
            self.by_topic[device.mqtt_topic] = device.id

    def _save(self, device: TasmotaDevice) -> TasmotaDevice:
        with SessionLocal() as db:
            device = db.merge(device)
            db.commit()
        self._register(device)
        return device

    def _create(self, **fields) -> TasmotaDevice:
        device = self._save(TasmotaDevice(**fields))
        log.info("Added Tasmota device %s", device.mqtt_topic or device.host)
        return device

    def _forget(self, device_id: int) -> None:
        device = self.devices.pop(device_id, None)
        self.live.pop(device_id, None)
        if device and device.mqtt_topic:
            self.by_topic.pop(device.mqtt_topic, None)

    def _find(self, *, topic: str | None = None, mac: str | None = None, host: str | None = None) -> TasmotaDevice | None:
        if topic and topic in self.by_topic:
            return self.devices[self.by_topic[topic]]
        for device in self.devices.values():
            if mac and device.mac == mac:
                return device
        for device in self.devices.values():
            if host and device.host == host:
                return device
        return None

    def _ensure_topic(self, topic: str, retained: bool) -> TasmotaDevice | None:
        device_id = self.by_topic.get(topic)
        if device_id is None:
            return self._create(mqtt_topic=topic, source="mqtt")
        device = self.devices[device_id]
        if device.removed:
            # Retained messages replay old state on every start; only a live message brings a device back.
            if retained:
                return None
            device.removed = False
            device = self._save(device)
            log.info("Removed device %s is active again", topic)
        return device

    def _apply(self, device: TasmotaDevice, update: Update, online: bool | None = None) -> TasmotaDevice:
        changed = False
        names = json.dumps(update.friendly_names) if update.friendly_names is not None else None
        for attr, value in (
            ("host", update.host),
            ("mac", update.mac),
            ("hostname", update.hostname),
            ("firmware", update.firmware),
            ("model", update.model),
            ("friendly_names", names),
        ):
            if value is not None and getattr(device, attr) != value:
                setattr(device, attr, value)
                changed = True

        if update.mac:
            device = self._absorb_duplicate(device, update.mac) or device

        now = utcnow()
        if online is not False and (device.last_seen is None or now - device.last_seen > LAST_SEEN_WRITE_INTERVAL):
            device.last_seen = now
            changed = True
        if changed:
            device = self._save(device)

        live = self.live.setdefault(device.id, LiveState())
        live.power.update(update.power)
        if update.sensors is not None:
            live.sensors = update.sensors
        if update.wifi is not None:
            live.wifi = update.wifi
        if update.uptime is not None:
            live.uptime = update.uptime
        if update.relay_count is not None:
            live.relay_count = update.relay_count
        if online is not None:
            live.online = online
        self._mark_dirty(device.id)
        return device

    def _absorb_duplicate(self, device: TasmotaDevice, mac: str) -> TasmotaDevice | None:
        """A device first found by the network scan (no topic) is merged into its MQTT entry."""
        for other in list(self.devices.values()):
            if other.id != device.id and other.mac == mac and not other.mqtt_topic:
                device.name = device.name or other.name
                device.group_name = device.group_name or other.group_name
                with SessionLocal() as db:
                    db.execute(delete(TasmotaDevice).where(TasmotaDevice.id == other.id))
                    db.commit()
                self._forget(other.id)
                self._broadcast({"type": "removed", "id": other.id})
                return self._save(device)
        return None

    # --- MQTT messages ------------------------------------------------------------

    def handle_message(self, topic: str, payload: bytes, retained: bool) -> None:
        parts = topic.split("/")

        if len(parts) == 4 and parts[:2] == ["tasmota", "discovery"]:
            self._handle_discovery(parts[2], parts[3], payload, retained)
            return
        if len(parts) != 3:
            return
        prefix, device_topic, suffix = parts

        console = self.consoles.get(self.by_topic.get(device_topic, -1))
        if console:
            console.mqtt_message(topic, payload, retained)

        if prefix == "tele":
            if suffix == "LWT":
                online = payload.decode(errors="replace").strip().lower() == "online"
                device = self._ensure_topic(device_topic, retained)
                if device:
                    self._apply(device, Update(), online=online)
                    if online:
                        self._query_status(device_topic)
                return
            parser = {"STATE": parse_state, "SENSOR": parse_sensor}.get(suffix)
            if parser:
                device = self._ensure_topic(device_topic, retained)
                if device:
                    self._apply(device, parser(payload), online=True)
            return

        if prefix != "stat" or device_topic not in self.by_topic:
            return
        device = self.devices[self.by_topic[device_topic]]
        if device.removed:
            return

        if suffix == "RESULT":
            update = parse_result(payload)
        elif suffix.startswith("POWER"):
            update = parse_power_message(suffix, payload)
        elif suffix.startswith("STATUS"):
            data = decode_json(payload)
            update = parse_status(data) if data else Update()
        else:
            return
        self._apply(device, update, online=True)
        self._resolve_power_waiters(device_topic, update)

    def _handle_discovery(self, mac_id: str, kind: str, payload: bytes, retained: bool) -> None:
        if kind == "config":
            update = parse_discovery_config(payload)
            if update.topic:
                device = self._ensure_topic(update.topic, retained)
                if device:
                    self._apply(device, update)
        elif kind == "sensors":
            device = self._find(mac=normalize_mac(mac_id))
            if device and not device.removed and self.live[device.id].sensors is None:
                self._apply(device, parse_discovery_sensors(payload))

    def _resolve_power_waiters(self, topic: str, update: Update) -> None:
        waiters = self._power_waiters.get(topic)
        if not waiters or not update.power:
            return
        for channel, future in list(waiters):
            if channel in update.power and not future.done():
                future.set_result(update.power[channel])

    # --- change notifications -----------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=LISTENER_QUEUE_SIZE)
        self._listeners.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._listeners.discard(queue)

    def _broadcast(self, message: dict[str, Any]) -> None:
        for queue in list(self._listeners):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # A slow client gets the full current state instead of the backlog it missed.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({"type": "resync"})

    def _mark_dirty(self, device_id: int) -> None:
        self._dirty.add(device_id)
        if self._notify_scheduled:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._notify_scheduled = True
        # A Status 0 answer arrives as up to a dozen messages; they are sent to browsers as one update.
        loop.call_later(NOTIFY_DELAY_SECONDS, self._flush_dirty)

    def _flush_dirty(self) -> None:
        self._notify_scheduled = False
        dirty, self._dirty = self._dirty, set()
        for device_id in dirty:
            device = self.devices.get(device_id)
            if device and not device.removed:
                self._broadcast({"type": "device", "device": self.view(device)})

    # --- views ------------------------------------------------------------------

    def view(self, device: TasmotaDevice) -> dict[str, Any]:
        live = self.live.get(device.id) or LiveState()
        names = json.loads(device.friendly_names) if device.friendly_names else []
        custom = json.loads(device.relay_names) if device.relay_names else []
        count = max(live.relay_count or 0, max(live.power, default=0))
        channels = []
        for channel in range(1, count + 1):
            device_label = (names[channel - 1] or None) if channel <= len(names) else None
            custom_label = (custom[channel - 1] or None) if channel <= len(custom) else None
            channels.append(
                {
                    "channel": channel,
                    "label": custom_label or device_label,
                    "custom_label": custom_label,
                    "device_label": device_label,
                    "state": live.power.get(channel),
                }
            )
        web_url = None
        if device.host:
            web_url = f"http://{device.host}" + (f":{device.port}" if device.port != 80 else "")
        return {
            "id": device.id,
            "name": device.name,
            "display_name": device.name or device.mqtt_topic or device.hostname or device.host or f"Device {device.id}",
            "friendly_name": (names[0] or None) if names else None,
            "topic": device.mqtt_topic,
            "host": device.host,
            "port": device.port,
            "mac": device.mac,
            "hostname": device.hostname,
            "firmware": device.firmware,
            "model": device.model,
            "group_name": device.group_name,
            "source": device.source,
            "auth_required": device.auth_required,
            "online": live.online,
            "last_seen": device.last_seen.isoformat() if device.last_seen else None,
            "channels": channels,
            "sensors": sensor_readings(live.sensors),
            "wifi": live.wifi,
            "uptime": live.uptime,
            "web_url": web_url,
        }

    def visible_devices(self) -> list[TasmotaDevice]:
        devices = [d for d in self.devices.values() if not d.removed]
        return sorted(devices, key=lambda d: ((d.group_name or "").lower(), self.view(d)["display_name"].lower()))

    def snapshot(self) -> list[dict[str, Any]]:
        return [self.view(device) for device in self.visible_devices()]

    def get(self, device_id: int) -> TasmotaDevice:
        device = self.devices.get(device_id)
        if device is None or device.removed:
            raise DeviceError("Device not found", 404)
        return device

    # --- consoles -------------------------------------------------------------------

    def open_console(self, device_id: int) -> tuple[DeviceConsole, asyncio.Queue]:
        device = self.get(device_id)
        console = self.consoles.get(device.id)
        if console is None:
            console = self.consoles[device.id] = DeviceConsole(self, device.id)
        return console, console.attach()

    def close_console(self, console: DeviceConsole, queue: asyncio.Queue) -> None:
        if console.detach(queue) and self.consoles.get(console.device_id) is console:
            del self.consoles[console.device_id]

    # --- credentials ----------------------------------------------------------------

    def credentials(self) -> Credentials | None:
        with SessionLocal() as db:
            rows = {
                row.key: row.value_enc
                for row in db.scalars(
                    select(AppSetting).where(AppSetting.key.in_([CREDENTIAL_USER_KEY, CREDENTIAL_PASSWORD_KEY]))
                )
            }
        if CREDENTIAL_USER_KEY not in rows:
            return None
        try:
            return Credentials(
                self.box.decrypt(rows[CREDENTIAL_USER_KEY]),
                self.box.decrypt(rows[CREDENTIAL_PASSWORD_KEY]) if CREDENTIAL_PASSWORD_KEY in rows else "",
            )
        except Exception:
            log.error("Stored Tasmota credentials cannot be decrypted; was the key file replaced?")
            return None

    def set_credentials(self, username: str | None, password: str | None) -> None:
        """username None clears the credentials; password None keeps the stored password."""
        with SessionLocal() as db:
            if username is None:
                db.execute(delete(AppSetting).where(AppSetting.key.in_([CREDENTIAL_USER_KEY, CREDENTIAL_PASSWORD_KEY])))
            else:
                db.merge(AppSetting(key=CREDENTIAL_USER_KEY, value_enc=self.box.encrypt(username), updated_at=utcnow()))
                if password is not None:
                    db.merge(
                        AppSetting(key=CREDENTIAL_PASSWORD_KEY, value_enc=self.box.encrypt(password), updated_at=utcnow())
                    )
            db.commit()

    # --- actions -------------------------------------------------------------------

    def uses_mqtt(self, device: TasmotaDevice) -> bool:
        return bool(device.mqtt_topic and self.mqtt_connected)

    async def set_power(self, device_id: int, channel: int, action: str) -> dict[str, Any]:
        device = self.get(device_id)
        live = self.live[device.id]
        if live.online is False:
            raise DeviceError("The device is offline", 409)
        command = f"POWER{channel}"

        if self.uses_mqtt(device):
            topic = device.mqtt_topic
            future = asyncio.get_running_loop().create_future()
            waiters = self._power_waiters.setdefault(topic, [])
            waiters.append((channel, future))
            try:
                await self.publish(f"cmnd/{topic}/{command}", action.upper())
                await asyncio.wait_for(future, POWER_TIMEOUT_SECONDS)
            except TimeoutError:
                raise DeviceError("The device did not confirm the command", 504) from None
            finally:
                waiters.remove((channel, future))
        else:
            data = await self.http_command(device, f"{command} {action.upper()}")
            self._apply(device, parse_result(json.dumps(data)), online=True)
        return self.view(self.devices[device.id])

    async def http_command(self, device: TasmotaDevice, command: str) -> dict[str, Any]:
        if not device.host:
            raise DeviceError("The device address is unknown and MQTT is not connected", 503)
        try:
            return await http_api.command(device.host, device.port, command, self.credentials())
        except AuthRequired:
            raise DeviceError("The device requires a login; set the shared Tasmota credentials", 502) from None
        except DeviceUnreachable:
            self._apply(device, Update(), online=False)
            raise DeviceError("The device did not respond", 504) from None

    async def refresh(self, device_id: int | None = None) -> None:
        devices = [self.get(device_id)] if device_id is not None else self.visible_devices()
        http_devices = []
        for device in devices:
            if self.uses_mqtt(device):
                await self.publish(f"cmnd/{device.mqtt_topic}/STATE")
                await self.publish(f"cmnd/{device.mqtt_topic}/Status", "10")
            elif device.host and not device.auth_required:
                http_devices.append(device)

        async def poll(device: TasmotaDevice) -> None:
            try:
                self._apply(device, parse_status(await self.http_command(device, "Status 0")), online=True)
            except DeviceError:
                pass

        await asyncio.gather(*(poll(device) for device in http_devices))

    async def scan(self) -> dict[str, Any]:
        subnet = self.settings.scan_subnet or await asyncio.to_thread(http_api.default_scan_subnet)
        hits = await http_api.scan(subnet, self.credentials())
        new = auth_required = 0

        for hit in hits:
            if hit.status is None:
                auth_required += 1
                device = self._find(host=hit.host)
                if device is None:
                    self._create(host=hit.host, source="scan", auth_required=True)
                    new += 1
                elif not device.auth_required:
                    device.auth_required = True
                    self._save(device)
                    self._mark_dirty(device.id)
                continue

            update = parse_status(hit.status)
            update.host = update.host or hit.host
            device = self._find(topic=update.topic, mac=update.mac, host=hit.host)
            if device is not None and device.removed:
                continue
            if device is None:
                topic = update.topic if update.topic and update.topic not in self.by_topic else None
                device = self._create(mqtt_topic=topic, host=hit.host, source="scan")
                new += 1
            if device.auth_required:
                device.auth_required = False
                device = self._save(device)
            self._apply(device, update, online=True)

        log.info("Network scan of %s: %d Tasmota devices, %d new, %d need login", subnet, len(hits), new, auth_required)
        return {"subnet": str(subnet), "found": len(hits), "new": new, "auth_required": auth_required}

    async def add_manual(self, name: str | None, host: str, port: int, group_name: str | None) -> dict[str, Any]:
        if not await asyncio.to_thread(http_api.is_local_address, host):
            raise DeviceError("The address must belong to a device in the local network")
        try:
            data = await http_api.command(host, port, "Status 0", self.credentials())
        except AuthRequired:
            raise DeviceError("The device requires a login; set the shared Tasmota credentials first") from None
        except DeviceUnreachable:
            raise DeviceError("The device did not respond; check the address") from None
        if not isinstance(data.get("Status"), dict):
            raise DeviceError("The device did not answer like a Tasmota device")

        update = parse_status(data)
        update.host = host
        existing = self._find(topic=update.topic, mac=update.mac)
        if existing is not None and not existing.removed:
            raise DeviceError(f"This device is already in the list as {self.view(existing)['display_name']}", 409)

        if existing is not None:
            existing.removed = False
            existing.name, existing.port, existing.group_name, existing.source = name, port, group_name, "manual"
            device = self._save(existing)
        else:
            topic = update.topic if update.topic and update.topic not in self.by_topic else None
            device = self._create(
                name=name, host=host, port=port, group_name=group_name, source="manual", mqtt_topic=topic
            )
        device = self._apply(device, update, online=True)
        if device.mqtt_topic and self.mqtt_connected:
            self._queried_topics.discard(device.mqtt_topic)
            self._query_status(device.mqtt_topic)
        self._flush_dirty()
        return self.view(device)

    def update_device(
        self, device_id: int, name: str | None, group_name: str | None, relay_names: list[str | None] | None = None
    ) -> dict[str, Any]:
        """relay_names None keeps the stored relay names; an empty entry falls back to the device's name."""
        device = self.get(device_id)
        device.name = name
        device.group_name = group_name
        if relay_names is not None:
            cleaned = clean_relay_names(relay_names)
            device.relay_names = json.dumps(cleaned) if cleaned else None
        device = self._save(device)
        self._mark_dirty(device.id)
        return self.view(device)

    def remove(self, device_id: int) -> None:
        device = self.get(device_id)
        if device.mqtt_topic:
            device.removed = True
            self._save(device)
            self.live[device.id] = LiveState()
        else:
            with SessionLocal() as db:
                db.execute(delete(TasmotaDevice).where(TasmotaDevice.id == device.id))
                db.commit()
            self._forget(device.id)
        self._broadcast({"type": "removed", "id": device_id})
        log.info("Removed Tasmota device %s", device.mqtt_topic or device.host)

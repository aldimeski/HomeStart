"""Zigbee devices behind a Tasmota Zigbee bridge (Zigbee2Tasmota).

The bridge reports its devices on its own topics: tele/<bridge>/SENSOR carries one object per device (keyed by
friendly name with SetOption83, by short address otherwise; wrapped in "ZbReceived" unless SetOption100), and
RESULT carries ZbState (pairing, joins), ZbMap pages and command answers. Zigbee state is kept in memory only:
"ZbInfo" returns every device with its last values, so it is rebuilt on start-up.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Any

SHORT_ADDRESS = re.compile(r"^0x[0-9A-Fa-f]{4}$")
BRIDGE_FIRMWARE = re.compile(r"zigbee|zbbrdg", re.IGNORECASE)

JOIN_SECONDS = 60
MAP_SCAN_SECONDS = 30
# ZbState status codes sent by Tasmota.
STATE_JOIN_DISABLED = 20
STATE_JOIN_ENABLED = 21
STATE_JOIN_UNTIL_REBOOT = 22
STATE_DEVICE_ANNOUNCED = (30, 34)

# Values that describe the device rather than a measurement.
META_KEYS = {
    "Device", "Name", "IEEEAddr", "ModelId", "Manufacturer", "Endpoints", "Endpoint", "Config", "Reachable",
    "LastSeen", "LastSeenEpoch", "LinkQuality", "BatteryPercentage", "BatteryLastSeenEpoch", "Power", "Dimmer",
    "Groups", "Group", "Cluster", "Command", "ParentNetwork", "Light",
}
UNITS = {
    "Temperature": "°C", "Humidity": "%", "Pressure": "hPa", "Illuminance": "lx", "BatteryVoltage": "V",
    "CO2": "ppm", "PM2.5": "µg/m³", "ActivePower": "W", "RMSVoltage": "V", "RMSCurrent": "A",
    "EnergyTotal": "kWh", "Distance": "cm",
}
BINARY_LABELS = {
    "Occupancy": ("Detected", "Clear"),
    "Contact": ("Closed", "Open"),
    "Water": ("Leak", "Dry"),
    "WaterLeak": ("Leak", "Dry"),
    "Smoke": ("Smoke", "Clear"),
    "Fire": ("Fire", "Clear"),
    "Vibration": ("Vibration", "Still"),
}


def is_bridge_firmware(firmware: str | None) -> bool:
    return bool(firmware and BRIDGE_FIRMWARE.search(firmware))


def device_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Zigbee device objects in a SENSOR or RESULT payload; empty when the payload is not about Zigbee devices."""
    if isinstance(data.get("ZbReceived"), dict):
        data = data["ZbReceived"]
    return [
        value
        for key, value in data.items()
        # Answers to Zb* commands (ZbMap pages, ZbState …) also carry a "Device" field but are not devices.
        if not key.startswith("Zb")
        and isinstance(value, dict)
        and isinstance(value.get("Device"), str)
        and SHORT_ADDRESS.match(value["Device"])
    ]


@dataclass
class ZigbeeDevice:
    short: str
    values: dict[str, Any] = field(default_factory=dict)

    def merge(self, entry: dict[str, Any]) -> None:
        self.values.update(entry)
        if "Power" in entry or "Dimmer" in entry or self._measurements():
            self.values["_updated"] = time.time()

    def _measurements(self) -> list[str]:
        return [key for key in self.values if key not in META_KEYS and not key.startswith("_") and "!" not in key]

    @property
    def kind(self) -> str:
        config = self.values.get("Config") or []
        if any(isinstance(item, str) and item[:1] in ("O", "L") for item in config):
            return "light"
        if any(key in UNITS or key in BINARY_LABELS for key in self.values):
            return "sensor"
        if "BatteryPercentage" in self.values:
            return "remote"
        return "other"

    def readings(self) -> list[dict[str, Any]]:
        rows = []
        for key in self._measurements():
            value = self.values[key]
            if key in BINARY_LABELS and isinstance(value, (bool, int)):
                rows.append({"name": key, "value": BINARY_LABELS[key][0 if value else 1], "unit": ""})
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                rows.append({"name": key, "value": value, "unit": UNITS.get(key, "")})
        return rows

    def view(self) -> dict[str, Any]:
        v = self.values
        power = v.get("Power")
        last_seen = v.get("LastSeenEpoch")
        return {
            "short": self.short,
            "name": v.get("Name") or None,
            "display_name": v.get("Name") or v.get("ModelId") or self.short,
            "ieee": v.get("IEEEAddr"),
            "model": v.get("ModelId"),
            "manufacturer": v.get("Manufacturer"),
            "kind": self.kind,
            "power": bool(power) if isinstance(power, (int, bool)) else None,
            "dimmer": v.get("Dimmer") if isinstance(v.get("Dimmer"), int) else None,
            "reachable": v.get("Reachable") if isinstance(v.get("Reachable"), bool) else None,
            "battery": v.get("BatteryPercentage") if isinstance(v.get("BatteryPercentage"), int) else None,
            "link_quality": v.get("LinkQuality") if isinstance(v.get("LinkQuality"), int) else None,
            "last_seen": int(last_seen) if isinstance(last_seen, (int, float)) and last_seen > 0 else None,
            "readings": self.readings(),
        }


@dataclass
class ZigbeeNetwork:
    devices: dict[str, ZigbeeDevice] = field(default_factory=dict)
    join_until: float | None = None  # epoch seconds; float("inf") until the bridge restarts
    map_pages: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    map_scanned_at: float | None = None
    map_scan_until: float | None = None

    def apply_entries(self, entries: list[dict[str, Any]]) -> list[str]:
        """Merges device objects; returns the short addresses that changed."""
        changed = []
        for entry in entries:
            short = entry["Device"].upper().replace("0X", "0x")
            self.devices.setdefault(short, ZigbeeDevice(short)).merge(entry)
            changed.append(short)
        return changed

    def apply_state(self, state: dict[str, Any], now: float) -> bool:
        """Handles ZbState; returns True when a device joined and the device list should be read again."""
        status = state.get("Status")
        if status == STATE_JOIN_DISABLED:
            self.join_until = None
        elif status == STATE_JOIN_ENABLED and not self.join_open(now):
            self.join_until = now + JOIN_SECONDS
        elif status == STATE_JOIN_UNTIL_REBOOT:
            self.join_until = float("inf")
        return status in STATE_DEVICE_ANNOUNCED

    def join_open(self, now: float) -> bool:
        return self.join_until is not None and now < self.join_until

    def start_map_scan(self, now: float) -> None:
        self.map_pages = {}
        self.map_scan_until = now + MAP_SCAN_SECONDS

    def apply_map_page(self, page: dict[str, Any], now: float) -> None:
        reporter = page.get("Device")
        if not isinstance(reporter, str) or not isinstance(page.get("Map"), list):
            return
        self.map_pages[(reporter.upper().replace("0X", "0x"), int(page.get("Start") or 0))] = page
        self.map_scanned_at = now

    def network_map(self) -> dict[str, Any] | None:
        """Nodes and links of the last ZbMap scan; each link keeps its best link quality."""
        if not self.map_pages:
            return None
        nodes: dict[str, dict[str, Any]] = {"0x0000": {"short": "0x0000", "type": "coordinator"}}
        links: dict[tuple[str, str], dict[str, Any]] = {}
        types = {"Coordinator": "coordinator", "Router": "router", "Device": "end_device"}
        for (reporter, _), page in self.map_pages.items():
            nodes.setdefault(reporter, {"short": reporter, "type": "router"})
            for neighbour in page["Map"]:
                short = str(neighbour.get("Device", "")).upper().replace("0X", "0x")
                if not SHORT_ADDRESS.match(short):
                    continue
                node = nodes.setdefault(short, {"short": short, "type": "end_device"})
                node["type"] = types.get(neighbour.get("DeviceType"), node["type"])
                key = tuple(sorted((reporter, short)))
                quality = neighbour.get("LinkQuality") if isinstance(neighbour.get("LinkQuality"), int) else None
                link = links.setdefault(key, {"a": key[0], "b": key[1], "link_quality": quality})
                if quality is not None and (link["link_quality"] or 0) < quality:
                    link["link_quality"] = quality
        for short, node in nodes.items():
            device = self.devices.get(short)
            node["name"] = device.view()["display_name"] if device else ("Bridge" if short == "0x0000" else None)
            node["known"] = short == "0x0000" or device is not None
        return {"nodes": list(nodes.values()), "links": list(links.values())}

    def view(self, now: float) -> dict[str, Any]:
        devices = sorted((d.view() for d in self.devices.values()), key=lambda d: d["display_name"].lower())
        join_left = None
        if self.join_open(now):
            join_left = None if self.join_until == float("inf") else max(0, round(self.join_until - now))
        return {
            "devices": devices,
            "join_open": self.join_open(now),
            "join_seconds_left": join_left,
            "map": self.network_map(),
            "map_scanned_at": self.map_scanned_at,
            "map_scanning": self.map_scan_until is not None and now < self.map_scan_until,
        }

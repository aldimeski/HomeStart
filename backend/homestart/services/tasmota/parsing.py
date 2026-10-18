"""Turns Tasmota MQTT/HTTP payloads into state updates.

Tasmota firmware differs between versions: e.g. 8.1.0 answers "Status 0" with separate
STATUS, STATUS1 … STATUS11 messages, newer builds may send one STATUS0 message, and the
HTTP API always returns one combined object. All of them use the same top-level keys
(Status, StatusFWR, StatusNET, StatusSNS, StatusSTS …), so they are handled key by key.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

POWER_KEY = re.compile(r"^POWER(\d*)$")
SKIPPED_SENSOR_KEYS = {"Time", "TempUnit", "PressureUnit", "SpeedUnit", "TotalStartTime"}

ENERGY_UNITS = {
    "Power": "W",
    "ApparentPower": "VA",
    "ReactivePower": "var",
    "Voltage": "V",
    "Current": "A",
    "Today": "kWh",
    "Yesterday": "kWh",
    "Total": "kWh",
    "Factor": "",
    "Frequency": "Hz",
}


@dataclass
class Update:
    """Everything one payload says about a device; None means "not mentioned"."""

    power: dict[int, str] = field(default_factory=dict)
    sensors: dict[str, Any] | None = None
    wifi: dict[str, int] | None = None
    uptime: str | None = None
    host: str | None = None
    mac: str | None = None
    hostname: str | None = None
    firmware: str | None = None
    model: str | None = None
    friendly_names: list[str] | None = None
    topic: str | None = None
    relay_count: int | None = None

    def is_empty(self) -> bool:
        return self == Update()


def decode_json(payload: bytes | str) -> dict[str, Any] | None:
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def normalize_mac(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"[^0-9A-Fa-f]", "", value).upper()
    if len(digits) != 12:
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def _power_channel(key: str) -> int | None:
    match = POWER_KEY.match(key)
    if not match:
        return None
    return int(match.group(1) or 1)


def _apply_power(update: Update, data: dict[str, Any]) -> None:
    for key, value in data.items():
        channel = _power_channel(key)
        if channel is not None and isinstance(value, str) and value.upper() in ("ON", "OFF"):
            update.power[channel] = value.upper()


def _apply_state(update: Update, data: dict[str, Any]) -> None:
    """tele/STATE, stat/RESULT and StatusSTS share this layout."""
    _apply_power(update, data)
    wifi = data.get("Wifi")
    if isinstance(wifi, dict):
        info = {}
        if isinstance(wifi.get("RSSI"), int):
            info["rssi"] = wifi["RSSI"]  # Tasmota reports RSSI as a 0–100 quality percentage
        if isinstance(wifi.get("Signal"), int):
            info["signal"] = wifi["Signal"]  # dBm
        if info:
            update.wifi = info
    if isinstance(data.get("Uptime"), str):
        update.uptime = data["Uptime"]


def clean_relay_names(names: list[Any]) -> list[str]:
    """Keeps positions (name N belongs to relay N); unused trailing entries are dropped."""
    cleaned = [str(name) if name else "" for name in names]
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return cleaned


def _clean_sensors(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key not in ("Time",)}


def parse_state(payload: bytes | str) -> Update:
    update = Update()
    data = decode_json(payload)
    if data:
        _apply_state(update, data)
    return update


def parse_sensor(payload: bytes | str) -> Update:
    data = decode_json(payload)
    return Update(sensors=_clean_sensors(data)) if data else Update()


def parse_result(payload: bytes | str) -> Update:
    """stat/<topic>/RESULT: a command answer, which may also be a full STATE."""
    return parse_state(payload)


def parse_power_message(suffix: str, payload: bytes | str) -> Update:
    """stat/<topic>/POWER or POWERn with a plain ON/OFF payload."""
    channel = _power_channel(suffix)
    text = payload.decode(errors="replace") if isinstance(payload, bytes) else payload
    update = Update()
    if channel is not None and text.strip().upper() in ("ON", "OFF"):
        update.power[channel] = text.strip().upper()
    return update


def parse_status(data: dict[str, Any]) -> Update:
    """Any Status answer: a single STATUSn message, a combined STATUS0, or the HTTP Status 0 reply."""
    update = Update()

    status = data.get("Status")
    if isinstance(status, dict):
        names = status.get("FriendlyName")
        if isinstance(names, list):
            update.friendly_names = clean_relay_names(names)
        if isinstance(status.get("Topic"), str):
            update.topic = status["Topic"]

    fwr = data.get("StatusFWR")
    if isinstance(fwr, dict) and isinstance(fwr.get("Version"), str):
        update.firmware = fwr["Version"]

    net = data.get("StatusNET")
    if isinstance(net, dict):
        if isinstance(net.get("IPAddress"), str) and net["IPAddress"] != "0.0.0.0":
            update.host = net["IPAddress"]
        update.mac = normalize_mac(net.get("Mac"))
        if isinstance(net.get("Hostname"), str):
            update.hostname = net["Hostname"]

    sns = data.get("StatusSNS")
    if isinstance(sns, dict):
        update.sensors = _clean_sensors(sns)

    sts = data.get("StatusSTS")
    if isinstance(sts, dict):
        _apply_state(update, sts)

    prm = data.get("StatusPRM")
    if isinstance(prm, dict) and update.uptime is None and isinstance(prm.get("Uptime"), str):
        update.uptime = prm["Uptime"]
    return update


def parse_discovery_config(payload: bytes | str) -> Update:
    """tasmota/discovery/<mac>/config, published (retained) by Tasmota 9+ with SetOption19 0."""
    data = decode_json(payload)
    if not data or not isinstance(data.get("t"), str):
        return Update()
    relays = data.get("rl")
    names = data.get("fn")
    return Update(
        topic=data["t"],
        host=data.get("ip") if isinstance(data.get("ip"), str) else None,
        mac=normalize_mac(data.get("mac")),
        hostname=data.get("hn") if isinstance(data.get("hn"), str) else None,
        firmware=data.get("sw") if isinstance(data.get("sw"), str) else None,
        model=data.get("md") if isinstance(data.get("md"), str) else None,
        friendly_names=clean_relay_names(names) if isinstance(names, list) else None,
        relay_count=sum(1 for r in relays if r) if isinstance(relays, list) else None,
    )


def parse_discovery_sensors(payload: bytes | str) -> Update:
    data = decode_json(payload)
    sensors = data.get("sn") if data else None
    return Update(sensors=_clean_sensors(sensors)) if isinstance(sensors, dict) else Update()


def sensor_readings(sensors: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flattens sensor data into display rows: {sensor, name, value, unit}."""
    if not sensors:
        return []
    temp_unit = f"°{sensors.get('TempUnit', 'C')}"
    pressure_unit = sensors.get("PressureUnit", "hPa")
    units = {
        "Temperature": temp_unit,
        "DewPoint": temp_unit,
        "Humidity": "%",
        "Pressure": pressure_unit,
        "SeaPressure": pressure_unit,
        "Illuminance": "lx",
        "CO2": "ppm",
        "eCO2": "ppm",
        "TVOC": "ppb",
        "Distance": "cm",
    }

    rows = []
    for sensor, values in sensors.items():
        if sensor in SKIPPED_SENSOR_KEYS or not isinstance(values, dict):
            continue
        for name, value in values.items():
            if name in SKIPPED_SENSOR_KEYS or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            unit = ENERGY_UNITS.get(name, "") if sensor == "ENERGY" else units.get(name, "")
            rows.append({"sensor": sensor, "name": name, "value": value, "unit": unit})
    return rows


def parse_console(text: str) -> tuple[int, list[str]] | None:
    """Answer of the web console endpoint /cs: "<index>}1<reset flag>}1<lines separated by \\n>}1".

    The same format is used from 7.x to 15.x; the index is passed back to get only newer lines.
    """
    parts = text.split("}1", 2)
    if len(parts) != 3 or not parts[0].isdigit():
        return None
    body = parts[2].removesuffix("}1")
    return int(parts[0]), [line for line in body.split("\n") if line.strip()]

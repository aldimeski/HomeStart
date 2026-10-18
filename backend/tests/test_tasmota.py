import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from homestart.config import load_settings
from homestart.main import create_app
from homestart.services.secret_box import SecretBox
from homestart.services.tasmota.manager import DeviceError, TasmotaManager
from homestart.services.tasmota.parsing import parse_discovery_config, parse_status, sensor_readings

CSRF = {"X-HomeStart": "1"}

# Payloads below are shortened copies of real messages from Tasmota 8.1.0, 7.2.0 and 15.0.1.
OLD_STATUS_MESSAGES = {
    "STATUS": {"Status": {"Module": 1, "FriendlyName": ["Sonoff grejanje"], "Topic": "grejanje", "Power": 0}},
    "STATUS2": {"StatusFWR": {"Version": "8.1.0(tasmota)", "Hardware": "ESP8266EX"}},
    "STATUS5": {
        "StatusNET": {"Hostname": "sonoff_grejanje", "IPAddress": "192.0.2.58", "Mac": "60:01:94:86:DE:E6"}
    },
    "STATUS10": {"StatusSNS": {"Time": "2026-10-18T10:11:00", "AM2301": {"Temperature": 20.5, "Humidity": 67.1}, "TempUnit": "C"}},
    "STATUS11": {
        "StatusSTS": {"Uptime": "15T01:04:55", "POWER": "OFF", "Wifi": {"RSSI": 74, "Signal": -63}}
    },
}

STATUS0_COMBINED = {
    "Status": {"FriendlyName": ["Sonoff Bathroom", "Sonoff2", "Sonoff3"], "Topic": "sonoff_bathroom"},
    "StatusFWR": {"Version": "15.0.1(release-lite)"},
    "StatusNET": {"Hostname": "sonoff-bathroom", "IPAddress": "192.0.2.59", "Mac": "DC:4F:22:82:16:A7"},
    "StatusSNS": {"Time": "2026-10-18T10:11:00"},
    "StatusSTS": {"POWER1": "ON", "POWER2": "OFF", "POWER3": "OFF", "Wifi": {"RSSI": 72, "Signal": -64}},
}


@pytest.fixture
def app_dir(tmp_path):
    (tmp_path / "homestart.ini").write_text("[database]\nfile = data/test.db\n[mqtt]\nenabled = false\n")
    return tmp_path


@pytest.fixture
def manager(app_dir):
    settings = load_settings(app_dir)
    create_app(settings)  # prepares the database and binds SessionLocal
    tasmota = TasmotaManager(settings, SecretBox.from_key_file(settings.key_file))
    tasmota.load()
    return tasmota


def send(manager, topic, payload, retained=False):
    data = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
    manager.handle_message(topic, data.encode() if isinstance(data, str) else data, retained)


def only_device(manager):
    devices = manager.snapshot()
    assert len(devices) == 1
    return devices[0]


# --- parsing -----------------------------------------------------------------


def test_split_and_combined_status_give_the_same_fields():
    merged = {}
    for payload in OLD_STATUS_MESSAGES.values():
        merged.update(payload)
    for data in (merged, STATUS0_COMBINED):
        update = parse_status(data)
        assert update.topic and update.firmware and update.host and update.mac and update.wifi


def test_sensor_readings_have_units():
    rows = sensor_readings(
        {"AM2301": {"Temperature": 21.5, "Humidity": 43.1}, "ENERGY": {"Power": 20, "TotalStartTime": "x"}, "TempUnit": "C"}
    )
    assert {"sensor": "AM2301", "name": "Temperature", "value": 21.5, "unit": "°C"} in rows
    assert {"sensor": "ENERGY", "name": "Power", "value": 20, "unit": "W"} in rows
    assert all(row["name"] != "TotalStartTime" for row in rows)


def test_discovery_config():
    update = parse_discovery_config(
        json.dumps({"ip": "192.0.2.52", "t": "radni_sto", "mac": "240AC40A3728", "md": "ESP32-DevKit", "sw": "15.0.1", "rl": [1, 0, 0]})
    )
    assert update.topic == "radni_sto"
    assert update.mac == "24:0A:C4:0A:37:28"
    assert update.relay_count == 1


# --- discovery and live state ------------------------------------------------


def test_lwt_discovers_device_and_old_firmware_status_is_merged(manager):
    send(manager, "tele/grejanje/LWT", "Online", retained=True)
    for suffix, payload in OLD_STATUS_MESSAGES.items():
        send(manager, f"stat/grejanje/{suffix}", payload)

    device = only_device(manager)
    assert device["display_name"] == "grejanje"
    assert device["online"] is True
    assert device["host"] == "192.0.2.58"
    assert device["firmware"] == "8.1.0(tasmota)"
    assert device["web_url"] == "http://192.0.2.58"
    assert device["channels"] == [
        {"channel": 1, "label": "Sonoff grejanje", "custom_label": None, "device_label": "Sonoff grejanje", "state": "OFF", "locked": False, "icon": None}
    ]
    assert device["wifi"] == {"rssi": 74, "signal": -63}
    assert {row["name"] for row in device["sensors"]} == {"Temperature", "Humidity"}


def test_combined_status0_and_multichannel_labels(manager):
    send(manager, "tele/sonoff_bathroom/LWT", "Online")
    send(manager, "stat/sonoff_bathroom/STATUS0", STATUS0_COMBINED)
    device = only_device(manager)
    assert [c["label"] for c in device["channels"]] == ["Sonoff Bathroom", "Sonoff2", "Sonoff3"]
    assert [c["state"] for c in device["channels"]] == ["ON", "OFF", "OFF"]


def test_power_updates_from_state_result_and_power_topics(manager):
    send(manager, "tele/tv/LWT", "Online")
    send(manager, "tele/tv/STATE", {"POWER": "ON", "Wifi": {"RSSI": 82}})
    assert only_device(manager)["channels"][0]["state"] == "ON"
    send(manager, "stat/tv/RESULT", {"POWER": "OFF"})
    assert only_device(manager)["channels"][0]["state"] == "OFF"
    send(manager, "stat/tv/POWER", "ON")
    assert only_device(manager)["channels"][0]["state"] == "ON"


def test_offline_device_stays_in_list(manager):
    send(manager, "tele/lamp/LWT", "Online")
    send(manager, "tele/lamp/LWT", "Offline")
    assert only_device(manager)["online"] is False


def test_unknown_stat_topic_is_ignored(manager):
    send(manager, "stat/unknown/RESULT", {"POWER": "ON"})
    assert manager.snapshot() == []


def test_removed_device_is_not_restored_by_retained_messages(manager, app_dir):
    send(manager, "tele/old/LWT", "Offline", retained=True)
    manager.remove(only_device(manager)["id"])
    assert manager.snapshot() == []

    # After a restart the broker replays the retained LWT; the device must stay removed.
    restarted = TasmotaManager(manager.settings, manager.box)
    restarted.load()
    send(restarted, "tele/old/LWT", "Offline", retained=True)
    assert restarted.snapshot() == []

    # A live message means the device is really back.
    send(restarted, "tele/old/LWT", "Online", retained=False)
    assert only_device(restarted)["online"] is True


def test_devices_and_names_survive_restart(manager):
    send(manager, "tele/grejanje/LWT", "Online")
    device_id = only_device(manager)["id"]
    manager.update_device(device_id, "Heating", "Living room")

    restarted = TasmotaManager(manager.settings, manager.box)
    restarted.load()
    device = only_device(restarted)
    assert device["display_name"] == "Heating"
    assert device["group_name"] == "Living room"
    assert device["online"] is None  # live state comes back from MQTT


async def test_power_on_offline_device_is_refused(manager):
    send(manager, "tele/lamp/LWT", "Offline")
    with pytest.raises(DeviceError) as error:
        await manager.set_power(only_device(manager)["id"], 1, "on")
    assert error.value.status_code == 409


# --- credentials -----------------------------------------------------------------


def test_credentials_are_encrypted(manager, app_dir):
    manager.set_credentials("admin", "s3cret-pass")
    assert manager.credentials().password == "s3cret-pass"
    raw = (app_dir / "data" / "test.db").read_bytes()
    assert b"s3cret-pass" not in raw

    manager.set_credentials("admin2", None)  # keep the stored password
    assert manager.credentials().username == "admin2"
    assert manager.credentials().password == "s3cret-pass"

    manager.set_credentials(None, None)
    assert manager.credentials() is None


# --- API -------------------------------------------------------------------------


@pytest.fixture
def client(app_dir):
    with TestClient(create_app(load_settings(app_dir))) as test_client:
        test_client.post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers=CSRF)
        yield test_client


def test_device_api_and_websocket_snapshot(client):
    client.app.state.tasmota.handle_message("tele/grejanje/LWT", b"Online", True)

    listing = client.get("/api/tasmota/devices").json()
    assert listing["mqtt_connected"] is False
    device_id = listing["devices"][0]["id"]

    assert client.put(f"/api/tasmota/devices/{device_id}", json={"name": " Heating ", "group_name": ""}, headers=CSRF).json()[
        "display_name"
    ] == "Heating"

    with client.websocket_connect("/ws/tasmota") as ws:
        message = ws.receive_json()
        assert message["type"] == "snapshot"
        assert message["devices"][0]["display_name"] == "Heating"

    assert client.delete(f"/api/tasmota/devices/{device_id}", headers=CSRF).status_code == 204
    assert client.get("/api/tasmota/devices").json()["devices"] == []


def test_credentials_api_never_returns_password(client):
    assert client.put("/api/tasmota/credentials", json={"username": "admin", "password": "pw"}, headers=CSRF).status_code == 204
    assert client.get("/api/tasmota/credentials").json() == {"username": "admin", "has_password": True}


def test_websocket_requires_login(app_dir):
    from starlette.websockets import WebSocketDisconnect

    with TestClient(create_app(load_settings(app_dir))) as anonymous:
        with pytest.raises(WebSocketDisconnect):
            with anonymous.websocket_connect("/ws/tasmota") as ws:
                ws.receive_json()


def test_manual_add_rejects_public_addresses(client):
    response = client.post("/api/tasmota/devices", json={"host": "8.8.8.8"}, headers=CSRF)
    assert response.status_code == 400


def test_non_admin_cannot_manage_devices(client):
    client.post("/api/users", json={"username": "ana", "password": "pass1234"}, headers=CSRF)
    client.post("/api/auth/logout", headers=CSRF)
    client.post("/api/auth/login", json={"username": "ana", "password": "pass1234"}, headers=CSRF)
    assert client.get("/api/tasmota/devices").status_code == 200
    assert client.post("/api/tasmota/scan", headers=CSRF).status_code == 403
    assert client.get("/api/tasmota/credentials").status_code == 403


def test_relay_names_keep_their_positions(manager):
    send(manager, "tele/desk/LWT", "Online")
    send(manager, "stat/desk/STATUS", {"Status": {"FriendlyName": ["", "Lamp", None], "Topic": "desk"}})
    send(manager, "stat/desk/RESULT", {"POWER1": "ON", "POWER2": "OFF", "POWER3": "OFF"})
    assert [c["label"] for c in only_device(manager)["channels"]] == [None, "Lamp", None]


class FakeMqtt:
    """Stands in for the broker: answers POWER commands like a Tasmota device would."""

    connected = True

    def __init__(self, manager, reply=True):
        self.manager = manager
        self.reply = reply
        self.published = []

    async def stop(self):
        pass

    async def publish(self, topic, payload=""):
        self.published.append((topic, payload))
        _, device_topic, command = topic.split("/")
        if self.reply and command.startswith("POWER"):
            state = "ON" if payload == "ON" else "OFF"
            asyncio.get_running_loop().call_soon(
                self.manager.handle_message, f"stat/{device_topic}/RESULT", json.dumps({command: state}).encode(), False
            )


async def test_power_command_waits_for_device_confirmation(manager):
    manager.mqtt = FakeMqtt(manager)
    send(manager, "tele/bath/LWT", "Online")
    send(manager, "stat/bath/RESULT", {"POWER1": "OFF", "POWER2": "OFF"})
    device = await manager.set_power(only_device(manager)["id"], 2, "on")
    assert manager.mqtt.published == [("cmnd/bath/POWER2", "ON")]
    assert [c["state"] for c in device["channels"]] == ["OFF", "ON"]


async def test_power_command_times_out_without_answer(manager, monkeypatch):
    from homestart.services.tasmota import manager as manager_module

    monkeypatch.setattr(manager_module, "POWER_TIMEOUT_SECONDS", 0.1)
    manager.mqtt = FakeMqtt(manager, reply=False)
    send(manager, "tele/lamp/LWT", "Online")
    with pytest.raises(DeviceError) as error:
        await manager.set_power(only_device(manager)["id"], 1, "toggle")
    assert error.value.status_code == 504


# --- relay names and consoles ------------------------------------------------------


def test_relay_names_set_in_homestart_override_device_names(client):
    manager = client.app.state.tasmota
    manager.handle_message("tele/bath/LWT", b"Online", False)
    manager.handle_message("stat/bath/STATUS0", json.dumps(STATUS0_COMBINED).encode(), False)
    device_id = client.get("/api/tasmota/devices").json()["devices"][0]["id"]

    body = {"name": None, "group_name": None, "relay_names": ["", " Mirror ", None]}
    channels = client.put(f"/api/tasmota/devices/{device_id}", json=body, headers=CSRF).json()["channels"]
    assert [c["label"] for c in channels] == ["Sonoff Bathroom", "Mirror", "Sonoff3"]
    assert [c["custom_label"] for c in channels] == [None, "Mirror", None]

    # Saving without relay_names (older clients) keeps them.
    channels = client.put(f"/api/tasmota/devices/{device_id}", json={"name": "Bath"}, headers=CSRF).json()["channels"]
    assert channels[1]["label"] == "Mirror"

    too_long = {"relay_names": ["x" * 65]}
    assert client.put(f"/api/tasmota/devices/{device_id}", json=too_long, headers=CSRF).status_code == 422


def test_parse_console_answer():
    from homestart.services.tasmota.parsing import parse_console

    text = '178}10}103:13:11 MQT: tele/tv/STATE = {"POWER":"ON"}\n03:18:11 MQT: tele/tv/SENSOR = {}}1'
    assert parse_console(text) == (178, ['03:13:11 MQT: tele/tv/STATE = {"POWER":"ON"}', "03:18:11 MQT: tele/tv/SENSOR = {}"])
    assert parse_console("178}11}1}1") == (178, [])
    assert parse_console("<html>Login</html>") is None


async def test_console_reads_http_log_incrementally(manager, monkeypatch):
    from homestart.services.tasmota import console as console_module

    calls = []

    async def fake_log(host, port, index, credentials, client):
        calls.append(index)
        return (index + 2, [f"line {index}", f"line {index + 1}"])

    monkeypatch.setattr(console_module.http_api, "console_log", fake_log)
    monkeypatch.setattr(console_module, "POLL_INTERVAL_SECONDS", 0.01)
    send(manager, "tele/desk/LWT", "Online")
    send(manager, "stat/desk/STATUS5", {"StatusNET": {"IPAddress": "192.0.2.10"}})

    console, queue = manager.open_console(only_device(manager)["id"])
    for _ in range(100):
        if len(calls) >= 3:
            break
        await asyncio.sleep(0.01)
    assert calls[:3] == [0, 2, 4]
    assert console.source == "http"
    # MQTT lines are not repeated: the device log already contains them.
    send(manager, "stat/desk/RESULT", {"POWER": "ON"})
    assert all("RESULT" not in line["text"] for line in console.history)

    manager.close_console(console, queue)
    assert manager.consoles == {}


async def test_console_without_http_shows_mqtt_and_sends_commands(manager, monkeypatch):
    from homestart.services.tasmota import console as console_module
    from homestart.services.tasmota.http_api import AuthRequired

    async def needs_login(*args):
        raise AuthRequired("192.0.2.11")

    monkeypatch.setattr(console_module.http_api, "console_log", needs_login)
    manager.mqtt = FakeMqtt(manager, reply=False)
    send(manager, "tele/lamp/LWT", "Online")
    send(manager, "stat/lamp/STATUS5", {"StatusNET": {"IPAddress": "192.0.2.11"}})

    console, queue = manager.open_console(only_device(manager)["id"])
    await asyncio.sleep(0.01)
    assert console.source == "mqtt" and "Configuration" in console.notice

    send(manager, "tele/lamp/INFO1", {"Module": "Generic"})
    send(manager, "tele/lamp/STATE", {"POWER": "OFF"}, retained=True)
    await console.command("Status 0", "admin")
    await console.command("Power/#", "admin")

    texts = [line["text"] for line in console.history]
    assert any("tele/lamp/INFO1" in text for text in texts)
    assert not any("tele/lamp/STATE" in text for text in texts)
    assert ("cmnd/lamp/Status", "0") in manager.mqtt.published
    assert [line["kind"] for line in console.history][-2:] == ["command", "error"]
    assert len(manager.mqtt.published) == 1  # the invalid command was not sent
    manager.close_console(console, queue)


def test_console_websocket_is_read_only_for_users(client):
    client.app.state.tasmota.handle_message("tele/lamp/LWT", b"Online", False)
    device_id = client.get("/api/tasmota/devices").json()["devices"][0]["id"]

    with client.websocket_connect(f"/ws/tasmota/console/{device_id}") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["can_write"] is True

    client.post("/api/users", json={"username": "ana", "password": "pass1234"}, headers=CSRF)
    client.post("/api/auth/logout", headers=CSRF)
    client.post("/api/auth/login", json={"username": "ana", "password": "pass1234"}, headers=CSRF)
    with client.websocket_connect(f"/ws/tasmota/console/{device_id}") as ws:
        assert ws.receive_json()["can_write"] is False
        ws.send_text(json.dumps({"type": "command", "command": "Restart 1"}))
        message = ws.receive_json()
        while message["type"] != "lines":
            message = ws.receive_json()
        assert message["lines"][0]["kind"] == "error"


def test_console_websocket_rejects_unknown_device(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws/tasmota/console/999") as ws:
            ws.receive_json()
    assert closed.value.code == 4404


# --- switch locks ------------------------------------------------------------------


def test_locked_switch_cannot_be_switched_until_an_admin_unlocks_it(client):
    manager = client.app.state.tasmota
    manager.mqtt = FakeMqtt(manager)
    manager.handle_message("tele/bath/LWT", b"Online", False)
    manager.handle_message("stat/bath/RESULT", b'{"POWER1":"OFF","POWER2":"OFF"}', False)
    device_id = client.get("/api/tasmota/devices").json()["devices"][0]["id"]

    channels = client.put(f"/api/tasmota/devices/{device_id}/lock", json={"channel": 2, "locked": True}, headers=CSRF).json()["channels"]
    assert [c["locked"] for c in channels] == [False, True]

    # Not even an administrator can switch it while it is locked.
    response = client.post(f"/api/tasmota/devices/{device_id}/power", json={"channel": 2, "action": "on"}, headers=CSRF)
    assert response.status_code == 423
    assert client.post(f"/api/tasmota/devices/{device_id}/power", json={"channel": 1, "action": "on"}, headers=CSRF).status_code == 200

    client.post("/api/users", json={"username": "ana", "password": "pass1234"}, headers=CSRF)
    client.post("/api/auth/logout", headers=CSRF)
    client.post("/api/auth/login", json={"username": "ana", "password": "pass1234"}, headers=CSRF)
    assert client.put(f"/api/tasmota/devices/{device_id}/lock", json={"channel": 2, "locked": False}, headers=CSRF).status_code == 403
    assert client.post(f"/api/tasmota/devices/{device_id}/power", json={"channel": 2, "action": "on"}, headers=CSRF).status_code == 423

    client.post("/api/auth/logout", headers=CSRF)
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers=CSRF)
    client.put(f"/api/tasmota/devices/{device_id}/lock", json={"channel": 2, "locked": False}, headers=CSRF)
    assert client.post(f"/api/tasmota/devices/{device_id}/power", json={"channel": 2, "action": "on"}, headers=CSRF).status_code == 200


def test_locks_survive_restart(manager):
    send(manager, "tele/lamp/LWT", "Online")
    send(manager, "stat/lamp/RESULT", {"POWER": "ON"})
    manager.set_lock(only_device(manager)["id"], 1, True, "admin")
    restarted = TasmotaManager(manager.settings, manager.box)
    restarted.load()
    send(restarted, "stat/lamp/RESULT", {"POWER": "ON"})
    assert restarted.snapshot()[0]["channels"][0]["locked"] is True


async def test_console_power_commands_respect_locks(manager):
    manager.mqtt = FakeMqtt(manager, reply=False)
    send(manager, "tele/desk/LWT", "Online")
    send(manager, "stat/desk/RESULT", {"POWER1": "OFF", "POWER2": "OFF"})
    device_id = only_device(manager)["id"]
    manager.set_lock(device_id, 2, True, "admin")
    console, queue = manager.open_console(device_id)

    for command in ["Power2 ON", "power0 off", "Backlog Power1 ON; Power2 TOGGLE"]:
        await console.command(command, "admin")
    assert manager.mqtt.published == []
    for command in ["Power2", "Power1 ON", "Backlog Power1 OFF; Status 0"]:
        await console.command(command, "admin")
    assert [topic for topic, _ in manager.mqtt.published] == ["cmnd/desk/Power2", "cmnd/desk/Power1", "cmnd/desk/Backlog"]
    manager.close_console(console, queue)


# --- icons -------------------------------------------------------------------------


def test_device_and_switch_icons(client):
    manager = client.app.state.tasmota
    manager.handle_message("tele/bath/LWT", b"Online", False)
    manager.handle_message("stat/bath/STATUS0", json.dumps(STATUS0_COMBINED).encode(), False)
    device_id = client.get("/api/tasmota/devices").json()["devices"][0]["id"]
    url = f"/api/tasmota/devices/{device_id}"

    body = {"name": None, "group_name": None, "icon": "builtin:gas-boiler", "relay_icons": ["mdi:lightbulb", "", None]}
    device = client.put(url, json=body, headers=CSRF).json()
    assert device["icon"] == "builtin:gas-boiler"
    assert [c["icon"] for c in device["channels"]] == ["mdi:lightbulb", None, None]

    # Omitted fields keep their values; an empty icon removes it.
    assert client.put(url, json={"name": "Bath"}, headers=CSRF).json()["icon"] == "builtin:gas-boiler"
    assert client.put(url, json={"name": "Bath", "icon": ""}, headers=CSRF).json()["icon"] is None
    assert client.put(url, json={"icon": "javascript:alert(1)"}, headers=CSRF).status_code == 422
    assert client.put(url, json={"relay_icons": ["mdi:Bad Name"]}, headers=CSRF).status_code == 422


def test_uploaded_icon_used_by_a_switch_cannot_be_deleted(client):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>'
    icon = client.post("/api/icons", files={"file": ("lamp.svg", svg, "image/svg+xml")}, headers=CSRF).json()["icon"]
    client.app.state.tasmota.handle_message("tele/lamp/LWT", b"Online", False)
    client.app.state.tasmota.handle_message("stat/lamp/RESULT", b'{"POWER":"ON"}', False)
    device_id = client.get("/api/tasmota/devices").json()["devices"][0]["id"]
    client.put(f"/api/tasmota/devices/{device_id}", json={"relay_icons": [icon]}, headers=CSRF)

    assert client.delete(f"/api/icons/{icon[7:]}", headers=CSRF).status_code == 409
    client.put(f"/api/tasmota/devices/{device_id}", json={"relay_icons": [None]}, headers=CSRF)
    assert client.delete(f"/api/icons/{icon[7:]}", headers=CSRF).status_code == 204

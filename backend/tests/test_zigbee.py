import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from homestart.config import load_settings
from homestart.main import create_app
from homestart.services.secret_box import SecretBox
from homestart.services.tasmota import manager as manager_module
from homestart.services.tasmota.manager import DeviceError, TasmotaManager

CSRF = {"X-HomeStart": "1"}

# Shortened copies of real messages from a Sonoff Zigbee Bridge Pro (Tasmota 15.1.0, SetOption83 and 100 on);
# IEEE addresses replaced.
BULB = {
    "LR_Ikea_LB1": {
        "Device": "0x6D57", "Name": "LR_Ikea_LB1", "IEEEAddr": "0x0000000000000001",
        "ModelId": "TRADFRI bulb E27 WW globe 806lm", "Manufacturer": "IKEA of Sweden", "Endpoints": [1, 242],
        "Config": ["O01", "L01"], "Power": 1, "Dimmer": 83, "Reachable": True, "LastSeenEpoch": 1792515121,
        "LinkQuality": 109,
    }
}
REMOTE = {
    "IK_Rodret_1": {
        "Device": "0x3719", "Name": "IK_Rodret_1", "IEEEAddr": "0x0000000000000002", "ModelId": "RODRET wireless dimmer",
        "Manufacturer": "IKEA of Sweden", "Endpoints": [1], "Config": [], "Reachable": False,
        "BatteryPercentage": 100, "LastSeenEpoch": 1791743714, "LinkQuality": 127,
    }
}
MAP_PAGES = [
    {"ZbMap": {"Device": "0x0000", "Status": 0, "Total": 4, "Start": 1, "Map": [
        {"Device": "0x4AAB", "DeviceType": "Device", "Relationship": "Child", "LinkQuality": 170},
        {"Device": "0xF02D", "Name": "IK_Styrbar_1", "DeviceType": "Device", "Relationship": "Child", "LinkQuality": 170},
    ]}},
    {"ZbMap": {"Device": "0x0000", "Status": 0, "Total": 4, "Start": 3, "Map": [
        {"Device": "0x3719", "Name": "IK_Rodret_1", "DeviceType": "Device", "Relationship": "Child", "LinkQuality": 170},
        {"Device": "0x6D57", "Name": "LR_Ikea_LB1", "DeviceType": "Router", "Relationship": "Sibling", "LinkQuality": 97},
    ]}},
    {"ZbMap": {"Device": "0x6D57", "Name": "LR_Ikea_LB1", "Status": 0, "Total": 1, "Start": 1, "Map": [
        {"Device": "0x0000", "DeviceType": "Coordinator", "Relationship": "Parent", "LinkQuality": 180},
    ]}},
]


@pytest.fixture
def app_dir(tmp_path):
    (tmp_path / "homestart.ini").write_text("[database]\nfile = data/test.db\n[mqtt]\nenabled = false\n")
    return tmp_path


class FakeMqtt:
    """Answers like the bridge: a ZbSend to a bulb comes back as a SENSOR report with the new Power."""

    connected = True

    def __init__(self, manager, reply=True):
        self.manager = manager
        self.reply = reply
        self.published = []

    async def stop(self):
        pass

    async def publish(self, topic, payload=""):
        self.published.append((topic, payload))
        if self.reply and topic.endswith("/ZbSend"):
            command = json.loads(payload)
            report = {"LR_Ikea_LB1": {"Device": command["Device"], "Power": 1 if command["Send"]["Power"] == "On" else 0}}
            asyncio.get_running_loop().call_soon(
                self.manager.handle_message, "tele/zigbee_bridge/SENSOR", json.dumps(report).encode(), False
            )


@pytest.fixture
def manager(app_dir):
    settings = load_settings(app_dir)
    create_app(settings)
    tasmota = TasmotaManager(settings, SecretBox.from_key_file(settings.key_file))
    tasmota.load()
    tasmota.mqtt = FakeMqtt(tasmota)
    return tasmota


def send(manager, topic, payload, retained=False):
    manager.handle_message(topic, json.dumps(payload).encode(), retained)


async def bridge(manager):
    send(manager, "tele/zigbee_bridge/LWT", "Online")
    send(manager, "tele/zigbee_bridge/SENSOR", BULB)
    send(manager, "tele/zigbee_bridge/SENSOR", REMOTE)
    await asyncio.sleep(0.01)  # lets the ZbInfo request go out
    return manager.snapshot()[0]


async def test_bridge_is_recognized_from_zigbee_messages(manager):
    device = await bridge(manager)
    devices = {d["short"]: d for d in device["zigbee"]["devices"]}
    assert devices["0x6D57"]["kind"] == "light" and devices["0x6D57"]["power"] is True
    assert devices["0x6D57"]["dimmer"] == 83
    assert devices["0x3719"]["kind"] == "remote" and devices["0x3719"]["battery"] == 100
    # Zigbee values are not shown as sensors of the bridge itself.
    assert device["sensors"] == []
    # The full device list is requested once when the bridge is found.
    assert ("cmnd/zigbee_bridge/ZbInfo", "") in manager.mqtt.published


async def test_bridge_is_recognized_from_firmware(manager):
    send(manager, "tele/zb/LWT", "Online")
    send(manager, "stat/zb/STATUS2", {"StatusFWR": {"Version": "15.1.0(release-zbbrdgpro)"}})
    assert manager.snapshot()[0]["zigbee"] == {
        "devices": [], "join_open": False, "join_seconds_left": None,
        "map": None, "map_scanned_at": None, "map_scanning": False,
    }


async def test_discovery_does_not_hide_the_bridge_build(manager):
    send(manager, "tele/zb/LWT", "Online")
    send(manager, "stat/zb/STATUS2", {"StatusFWR": {"Version": "15.1.0(release-zbbrdgpro)"}})
    send(manager, "tasmota/discovery/AABBCCDDEEFF/config", {"t": "zb", "sw": "15.1.0", "ip": "192.0.2.79"})
    assert manager.snapshot()[0]["firmware"] == "15.1.0(release-zbbrdgpro)"


async def test_wrapped_messages_and_sensor_readings(manager):
    send(manager, "tele/zigbee_bridge/LWT", "Online")
    send(manager, "tele/zigbee_bridge/SENSOR", {"ZbReceived": {"0xA1B2": {
        "Device": "0xA1B2", "Temperature": 21.4, "Humidity": 55, "Occupancy": 1, "BatteryPercentage": 87, "Endpoint": 1,
    }}})
    sensor = manager.snapshot()[0]["zigbee"]["devices"][0]
    assert sensor["kind"] == "sensor"
    assert {r["name"]: (r["value"], r["unit"]) for r in sensor["readings"]} == {
        "Temperature": (21.4, "°C"), "Humidity": (55, "%"), "Occupancy": ("Detected", ""),
    }


async def test_switching_a_zigbee_light_waits_for_the_report(manager):
    device = await bridge(manager)
    result = await manager.zigbee_power(device["id"], "0x6D57", "toggle")
    assert manager.mqtt.published[-1] == ("cmnd/zigbee_bridge/ZbSend", '{"Device": "0x6D57", "Send": {"Power": "Off"}}')
    assert {d["short"]: d["power"] for d in result["zigbee"]["devices"]}["0x6D57"] is False

    with pytest.raises(DeviceError) as error:
        await manager.zigbee_power(device["id"], "0x3719", "on")  # a remote has nothing to switch
    assert error.value.status_code == 400


async def test_switching_times_out_without_report(manager, monkeypatch):
    monkeypatch.setattr(manager_module, "ZIGBEE_POWER_TIMEOUT_SECONDS", 0.1)
    device = await bridge(manager)
    manager.mqtt.reply = False
    with pytest.raises(DeviceError) as error:
        await manager.zigbee_power(device["id"], "0x6D57", "on")
    assert error.value.status_code == 504


async def test_join_opens_for_sixty_seconds_and_follows_zbstate(manager):
    device = await bridge(manager)
    result = await manager.zigbee_join(device["id"], True, "admin")
    assert manager.mqtt.published[-1] == ("cmnd/zigbee_bridge/ZbPermitJoin", "1")
    assert result["zigbee"]["join_open"] and 58 <= result["zigbee"]["join_seconds_left"] <= 60

    send(manager, "tele/zigbee_bridge/RESULT", {"ZbState": {"Status": 20, "Message": "Pairing mode disabled"}})
    assert manager.snapshot()[0]["zigbee"]["join_open"] is False

    send(manager, "tele/zigbee_bridge/RESULT", {"ZbState": {"Status": 30, "IEEEAddr": "0x0000000000000003"}})
    await asyncio.sleep(0)  # a joined device makes HomeStart read the list again a little later
    assert any(task for task in manager._tasks if not task.done())


async def test_network_map_from_zbmap_pages(manager):
    device = await bridge(manager)
    await manager.zigbee_map(device["id"])
    assert manager.mqtt.published[-1] == ("cmnd/zigbee_bridge/ZbMap", "")
    assert manager.snapshot()[0]["zigbee"]["map_scanning"] is True
    for page in MAP_PAGES:
        send(manager, "tele/zigbee_bridge/RESULT", page)

    zigbee = manager.snapshot()[0]["zigbee"]
    # Map pages are not devices and do not change the devices' values.
    assert sorted(d["short"] for d in zigbee["devices"]) == ["0x3719", "0x6D57"]
    assert "Total" not in str(zigbee["devices"])
    network_map = zigbee["map"]
    nodes = {node["short"]: node for node in network_map["nodes"]}
    assert nodes["0x0000"]["type"] == "coordinator" and nodes["0x6D57"]["type"] == "router"
    assert nodes["0x4AAB"]["known"] is False and nodes["0x3719"]["name"] == "IK_Rodret_1"
    assert nodes["0x0000"]["name"] == "Bridge"
    links = {(link["a"], link["b"]): link["link_quality"] for link in network_map["links"]}
    assert links[("0x0000", "0x6D57")] == 180  # the better of both directions
    assert len(links) == 4


async def test_retained_zigbee_messages_are_ignored(manager):
    send(manager, "tele/zigbee_bridge/LWT", "Online")
    send(manager, "tele/zigbee_bridge/SENSOR", BULB, retained=True)
    assert manager.snapshot()[0]["zigbee"] is None


def test_zigbee_api_permissions(app_dir):
    with TestClient(create_app(load_settings(app_dir))) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers=CSRF)
        manager = client.app.state.tasmota
        manager.handle_message("tele/zigbee_bridge/LWT", b"Online", False)
        manager.handle_message("tele/zigbee_bridge/SENSOR", json.dumps(BULB).encode(), False)
        device_id = client.get("/api/tasmota/devices").json()["devices"][0]["id"]

        # Without MQTT nothing can be sent to the bridge.
        response = client.put(f"/api/tasmota/devices/{device_id}/zigbee/join", json={"enabled": True}, headers=CSRF)
        assert response.status_code == 503
        assert client.post(f"/api/tasmota/devices/{device_id}/zigbee/0xZZZZ/power", json={"action": "on"}, headers=CSRF).status_code == 422

        client.post("/api/users", json={"username": "ana", "password": "pass1234"}, headers=CSRF)
        client.post("/api/auth/logout", headers=CSRF)
        client.post("/api/auth/login", json={"username": "ana", "password": "pass1234"}, headers=CSRF)
        assert client.put(f"/api/tasmota/devices/{device_id}/zigbee/join", json={"enabled": True}, headers=CSRF).status_code == 403
        assert client.post(f"/api/tasmota/devices/{device_id}/zigbee/map", headers=CSRF).status_code == 403
        # Users may switch lights (here refused only because MQTT is off in tests).
        assert client.post(f"/api/tasmota/devices/{device_id}/zigbee/0x6D57/power", json={"action": "on"}, headers=CSRF).status_code == 503

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from myskoda.models.driving_range import DrivingRange
from myskoda.models.health import Health
from myskoda.models.position import ParkingPositionV3
from myskoda.models.status import Status

from homestart.api import map_tiles
from homestart.config import load_settings
from homestart.main import create_app
from homestart.models import utcnow
from homestart.services.skoda import service as service_module
from homestart.services.skoda.client import FetchResult, SkodaLoginError, SkodaUnavailable, vehicle_data

CSRF = {"X-HomeStart": "1"}
VIN = "TMBJJ7NE0L0000001"  # made-up VIN in the Škoda format

RENDER = "https://example.invalid/render.png?vehicleState=1-3-2-1-0-0-0-0"  # front right door open, rear left window open
STATUS = {
    "detail": {"bonnet": "CLOSED", "sunroof": "UNSUPPORTED", "trunk": "OPEN"},
    "overall": {"doors": "OPEN", "doorsLocked": "OPENED", "lights": "OFF", "locked": "NO", "windows": "OPEN"},
    "renders": {
        "lightMode": {"oneX": RENDER, "oneAndHalfX": RENDER, "twoX": RENDER, "threeX": RENDER},
        "darkMode": {"oneX": RENDER, "oneAndHalfX": RENDER, "twoX": RENDER, "threeX": RENDER},
    },
    "carCapturedTimestamp": "2026-10-20T08:00:00Z",
}
PARKING = {
    "parkingPosition": {
        "gpsCoordinates": {"latitude": 44.8125, "longitude": 20.4612},
        "formattedAddress": "Example street 1, Example city",
    }
}
RANGE = {
    "carType": "gasoline",
    "primaryEngineRange": {"engineType": "gasoline", "currentFuelLevelInPercent": 64, "remainingRangeInKm": 540},
    "totalRangeInKm": 540,
}


def test_vehicle_data_from_library_models():
    info = SimpleNamespace(
        name="Family car",
        specification=SimpleNamespace(title="Škoda Octavia Combi", model="Octavia", model_year="2021", body="Combi"),
        license_plate="XX-000-XX",
        renders=[SimpleNamespace(url="https://example.invalid/side.png", view_point="EXTERIOR_SIDE")],
    )
    data = vehicle_data(
        VIN,
        info,
        Status.from_dict(STATUS),
        ParkingPositionV3.from_dict(PARKING),
        DrivingRange.from_dict(RANGE),
        Health.from_dict({"mileageInKm": 81234, "warningLights": []}),
    )
    assert data["title"] == "Škoda Octavia Combi" and data["license_plate"] == "XX-000-XX"
    assert data["doors"] == {"front_left": "closed", "front_right": "open", "rear_left": "closed", "rear_right": "closed"}
    assert data["windows"]["rear_left"] == "open" and data["windows"]["front_left"] == "closed"
    assert (data["trunk"], data["bonnet"], data["sunroof"]) == ("open", "closed", "unsupported")
    assert data["lock"] == "unlocked" and data["lights"] == "off"
    assert data["position"]["address"] == "Example street 1, Example city"
    assert (data["mileage_km"], data["fuel_percent"], data["range_km"]) == (81234, 64, 540)
    assert data["image_url"] == "https://example.invalid/side.png"
    assert data["unavailable"] == []


def test_missing_parts_are_listed():
    data = vehicle_data(VIN, None, None, None, None, None)
    assert data["unavailable"] == [
        "vehicle details",
        "doors and lock status",
        "parking position",
        "range and fuel level",
        "mileage",
    ]


class FakeSkoda:
    """Stands in for the MyŠkoda servers."""

    def __init__(self):
        self.calls = []
        self.error: Exception | None = None

    async def __call__(self, username, password, refresh_token):
        self.calls.append((username, password, refresh_token))
        if self.error:
            raise self.error
        data = vehicle_data(VIN, None, Status.from_dict(STATUS), ParkingPositionV3.from_dict(PARKING), None, None)
        data["name"] = "Family car"
        return FetchResult(f"token-{len(self.calls)}", [data])


@pytest.fixture
def app_dir(tmp_path):
    (tmp_path / "homestart.ini").write_text("[database]\nfile = data/test.db\n[mqtt]\nenabled = false\n")
    return tmp_path


@pytest.fixture
def client(app_dir):
    with TestClient(create_app(load_settings(app_dir))) as test_client:
        test_client.post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers=CSRF)
        test_client.fake = FakeSkoda()
        test_client.app.state.skoda._fetch = test_client.fake
        yield test_client


def connect(client, password="secret-pass"):
    return client.put("/api/skoda/account", json={"username": "driver@example.invalid", "password": password}, headers=CSRF)


def test_connect_stores_login_encrypted_and_caches_vehicles(client, app_dir):
    assert client.get("/api/skoda/vehicles").json() == {"account": {"connected": False}, "vehicles": []}

    body = connect(client).json()
    assert body["account"]["connected"] and body["account"]["username"] == "driver@example.invalid"
    vehicle = body["vehicles"][0]
    assert vehicle["vin"] == VIN and vehicle["trunk"] == "open" and "image_url" not in vehicle

    raw = (app_dir / "data" / "test.db").read_bytes()
    for secret in (b"secret-pass", b"driver@example.invalid", b"token-1"):
        assert secret not in raw


def test_refresh_rules(client):
    connect(client)
    fake = client.fake
    # Connecting counts as the first fetch of this login.
    assert client.post("/api/skoda/refresh", json={}, headers=CSRF).json()["refreshed"] is False

    assert client.post("/api/skoda/refresh", json={"force": True}, headers=CSRF).json()["refreshed"] is True
    assert fake.calls[-1] == ("driver@example.invalid", "secret-pass", "token-1")  # stored session reused

    # A new HomeStart login fetches again on the first visit.
    client.post("/api/auth/logout", headers=CSRF)
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers=CSRF)
    assert client.post("/api/skoda/refresh", json={}, headers=CSRF).json()["refreshed"] is True
    assert client.post("/api/skoda/refresh", json={}, headers=CSRF).json()["refreshed"] is False

    # After 15 minutes opening the page fetches again.
    service = client.app.state.skoda
    with service_module.SessionLocal() as db:
        account = db.scalars(service_module.select(service_module.SkodaAccount)).one()
        account.last_attempt = utcnow() - service_module.AUTO_REFRESH_AFTER
        db.commit()
    assert client.post("/api/skoda/refresh", json={}, headers=CSRF).json()["refreshed"] is True


def test_failed_refresh_keeps_cached_data(client):
    connect(client)
    client.fake.error = SkodaUnavailable("The Škoda servers cannot be reached right now.")
    body = client.post("/api/skoda/refresh", json={"force": True}, headers=CSRF).json()
    assert body["account"]["last_error"] == "The Škoda servers cannot be reached right now."
    assert body["vehicles"][0]["vin"] == VIN

    client.fake.error = None
    body = client.post("/api/skoda/refresh", json={"force": True}, headers=CSRF).json()
    assert body["account"]["last_error"] is None


def test_wrong_password_is_reported_and_not_stored(client):
    client.fake.error = SkodaLoginError("The MyŠkoda account rejected the email address or password.")
    response = connect(client, password="wrong")
    assert response.status_code == 400
    assert "rejected" in response.json()["detail"]
    assert client.get("/api/skoda/vehicles").json()["account"] == {"connected": False}


def test_each_user_sees_only_their_own_account(client):
    connect(client)
    client.post("/api/users", json={"username": "ana", "password": "pass1234"}, headers=CSRF)
    client.post("/api/auth/logout", headers=CSRF)
    client.post("/api/auth/login", json={"username": "ana", "password": "pass1234"}, headers=CSRF)
    assert client.get("/api/skoda/vehicles").json()["vehicles"] == []
    assert client.get(f"/api/skoda/vehicles/{VIN}/image").status_code == 404
    assert client.post("/api/skoda/refresh", json={}, headers=CSRF).status_code == 404


def test_sign_out_removes_everything(client, monkeypatch):
    async def fake_image(self, url, old_file):
        self.images_dir.mkdir(parents=True, exist_ok=True)
        (self.images_dir / "car.png").write_bytes(b"\x89PNG fake")
        return "car.png"

    monkeypatch.setattr(service_module.SkodaService, "_download_image", fake_image)
    original = client.fake.__call__

    async def with_image(username, password, refresh_token):
        result = await original(username, password, refresh_token)
        result.vehicles[0]["image_url"] = "https://example.invalid/side.png"
        return result

    client.app.state.skoda._fetch = with_image
    connect(client)
    assert client.get(f"/api/skoda/vehicles/{VIN}/image").content == b"\x89PNG fake"

    assert client.delete("/api/skoda/account", headers=CSRF).status_code == 204
    assert client.get("/api/skoda/vehicles").json()["account"] == {"connected": False}
    assert not (client.app.state.skoda.images_dir / "car.png").exists()


def test_skoda_api_requires_login(app_dir):
    with TestClient(create_app(load_settings(app_dir))) as anonymous:
        assert anonymous.get("/api/skoda/vehicles").status_code == 401
        assert anonymous.get("/api/map/tiles/1/0/0.png").status_code == 401


def test_map_tiles_are_cached(client, monkeypatch):
    downloads = []

    async def fake_download(url):
        downloads.append(url)
        return b"\x89PNG tile"

    monkeypatch.setattr(map_tiles, "download_tile", fake_download)
    assert client.get("/api/map/tiles/12/2275/1474.png").content == b"\x89PNG tile"
    assert client.get("/api/map/tiles/12/2275/1474.png").content == b"\x89PNG tile"
    assert downloads == ["https://tile.openstreetmap.org/12/2275/1474.png"]
    assert client.get("/api/map/tiles/1/2/0.png").status_code == 404  # x out of range at zoom 1
    assert client.get("/api/map/tiles/20/0/0.png").status_code == 404

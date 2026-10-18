import pytest
from fastapi.testclient import TestClient

from homestart.config import ConfigError, load_settings
from homestart.main import create_app
from homestart.services.svg_sanitizer import SvgError, sanitize_svg

CSRF = {"X-HomeStart": "1"}


@pytest.fixture
def app_dir(tmp_path):
    return tmp_path


@pytest.fixture
def client(app_dir):
    (app_dir / "homestart.ini").write_text("[database]\nfile = data/test.db\n[mqtt]\nenabled = false\n")
    app = create_app(load_settings(app_dir))
    with TestClient(app) as test_client:
        yield test_client


def login(client, username="admin", password="admin"):
    return client.post("/api/auth/login", json={"username": username, "password": password}, headers=CSRF)


# --- configuration ---------------------------------------------------------


def test_default_ini_is_created(app_dir):
    settings = load_settings(app_dir)
    assert settings.ini_file.name == "homestart_default.ini"
    assert settings.db_file == app_dir / "data" / "homestart.db"


def test_user_ini_takes_precedence(app_dir):
    (app_dir / "homestart.ini").write_text("[database]\nfile = custom/my.db\n")
    settings = load_settings(app_dir)
    assert settings.ini_file.name == "homestart.ini"
    assert settings.db_file == app_dir / "custom" / "my.db"


@pytest.mark.parametrize(
    "content",
    ["[server]\nport = 8000\n", "not an ini file", "[database]\nfile =\n", "[database]\nfile = x.db\n[server]\nport = abc\n"],
)
def test_invalid_user_ini_is_rejected(app_dir, content):
    (app_dir / "homestart.ini").write_text(content)
    with pytest.raises(ConfigError):
        load_settings(app_dir)
    assert not (app_dir / "homestart_default.ini").exists()


# --- authentication --------------------------------------------------------


def test_requires_login(client):
    assert client.get("/api/links").status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_initial_admin_login_and_logout(client):
    response = login(client)
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie

    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout", headers=CSRF).status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_post_without_csrf_header_is_rejected(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 403


def test_lockout_after_failed_attempts(client):
    for _ in range(5):
        assert login(client, password="wrong").status_code == 401
    locked = login(client)
    assert locked.status_code == 429
    assert "Retry-After" in locked.headers


def test_password_change(client):
    login(client)
    bad = client.post(
        "/api/users/me/password", json={"current_password": "nope", "new_password": "secret1"}, headers=CSRF
    )
    assert bad.status_code == 400
    ok = client.post(
        "/api/users/me/password", json={"current_password": "admin", "new_password": "secret1"}, headers=CSRF
    )
    assert ok.status_code == 204
    client.post("/api/auth/logout", headers=CSRF)
    assert login(client).status_code == 401
    assert login(client, password="secret1").status_code == 200


def test_settings_are_saved_per_user(client):
    login(client)
    response = client.put(
        "/api/users/me/settings", json={"theme": "dark", "sidebar_collapsed": True}, headers=CSRF
    )
    assert response.json() == {"theme": "dark", "sidebar_collapsed": True, "sholink_expanded": True}
    assert client.get("/api/auth/me").json()["settings"]["theme"] == "dark"


# --- users -----------------------------------------------------------------


def test_user_management_and_roles(client):
    login(client)
    created = client.post("/api/users", json={"username": "ana", "password": "pass1234"}, headers=CSRF)
    assert created.status_code == 201
    assert client.post("/api/users", json={"username": "ANA", "password": "pass1234"}, headers=CSRF).status_code == 409

    client.post("/api/auth/logout", headers=CSRF)
    assert login(client, "ana", "pass1234").status_code == 200
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/links", json={"title": "x", "url": "http://a"}, headers=CSRF).status_code == 403
    assert client.get("/api/links").status_code == 200


def test_last_admin_is_protected(client):
    admin_id = login(client).json()["user"]["id"]
    assert client.put(f"/api/users/{admin_id}", json={"role": "user"}, headers=CSRF).status_code == 400
    assert client.delete(f"/api/users/{admin_id}", headers=CSRF).status_code == 400


def test_deactivated_user_cannot_login(client):
    login(client)
    user_id = client.post("/api/users", json={"username": "bob", "password": "pass1234"}, headers=CSRF).json()["id"]
    client.put(f"/api/users/{user_id}", json={"is_active": False}, headers=CSRF)
    client.post("/api/auth/logout", headers=CSRF)
    assert login(client, "bob", "pass1234").status_code == 401


# --- links -----------------------------------------------------------------


def test_link_crud_and_order(client):
    login(client)
    first = client.post(
        "/api/links", json={"title": "openHAB", "url": "http://192.0.2.10:8080", "icon": "mdi:home"}, headers=CSRF
    ).json()
    assert first["open_in_new_tab"] is False
    second = client.post("/api/links", json={"title": "Router", "url": "http://192.0.2.1"}, headers=CSRF).json()

    reordered = client.put("/api/links/order", json={"ids": [second["id"], first["id"]]}, headers=CSRF)
    assert [link["title"] for link in reordered.json()] == ["Router", "openHAB"]
    assert [link["title"] for link in client.get("/api/links").json()] == ["Router", "openHAB"]

    updated = client.put(
        f"/api/links/{first['id']}",
        json={"title": "OH", "url": "https://192.0.2.10", "icon": "mdi:home", "open_in_new_tab": True},
        headers=CSRF,
    )
    assert updated.json()["open_in_new_tab"] is True
    assert client.delete(f"/api/links/{first['id']}", headers=CSRF).status_code == 204
    assert len(client.get("/api/links").json()) == 1


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://host", "http://", "http://user:pw@host"])
def test_invalid_link_urls_are_rejected(client, url):
    login(client)
    assert client.post("/api/links", json={"title": "x", "url": url}, headers=CSRF).status_code == 422


def test_builtin_icon_reference_is_accepted(client):
    login(client)
    response = client.post(
        "/api/links", json={"title": "Plug", "url": "http://192.0.2.20", "icon": "builtin:sonoff"}, headers=CSRF
    )
    assert response.status_code == 201
    assert response.json()["icon"] == "builtin:sonoff"


def test_invalid_icon_reference_is_rejected(client):
    login(client)
    response = client.post(
        "/api/links", json={"title": "x", "url": "http://a", "icon": "upload:../../etc/passwd"}, headers=CSRF
    )
    assert response.status_code == 422


# --- icons -----------------------------------------------------------------


def test_svg_upload_is_sanitized(client):
    login(client)
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" onload="alert(1)">'
        b'<script>alert(1)</script><path d="M0 0h24v24H0z" fill="red"/>'
        b'<image href="http://evil.example/x.png"/><a href="javascript:alert(1)"><rect width="1" height="1"/></a>'
        b"</svg>"
    )
    response = client.post("/api/icons", files={"file": ("logo.svg", svg, "image/svg+xml")}, headers=CSRF)
    assert response.status_code == 201
    name = response.json()["icon"].removeprefix("upload:")

    served = client.get(f"/api/icons/{name}")
    assert served.headers["content-type"] == "image/svg+xml"
    body = served.content.lower()
    for forbidden in (b"script", b"onload", b"evil.example", b"javascript", b"<image"):
        assert forbidden not in body
    assert b"<path" in body


def test_icon_upload_limits(client):
    login(client)
    too_big = b"\x89PNG\r\n\x1a\n" + b"0" * (256 * 1024)
    assert client.post("/api/icons", files={"file": ("a.png", too_big)}, headers=CSRF).status_code == 413
    assert client.post("/api/icons", files={"file": ("a.txt", b"hello")}, headers=CSRF).status_code == 415


def test_svg_sanitizer_rejects_entities():
    with pytest.raises(SvgError):
        sanitize_svg(b'<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>')


def test_svg_sanitizer_drops_external_css_urls():
    cleaned = sanitize_svg(
        b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(http://evil/x)" fill="url(#g)"/></svg>'
    )
    assert b"evil" not in cleaned and b"url(#g)" in cleaned


# --- embed check -------------------------------------------------------------


@pytest.mark.parametrize(
    ("headers", "blocked"),
    [
        ({}, False),
        ({"X-Frame-Options": "DENY"}, True),
        ({"X-Frame-Options": "sameorigin"}, True),
        ({"Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'"}, True),
        ({"Content-Security-Policy": "frame-ancestors *"}, False),
        ({"Content-Security-Policy": "frame-ancestors http://192.0.2.5:8000"}, False),
    ],
)
def test_frame_blocked_reason(headers, blocked):
    import httpx

    from homestart.api.links import _frame_blocked_reason

    reason = _frame_blocked_reason(httpx.Headers(headers), "http://192.0.2.5:8000", "http://192.0.2.9:8080")
    assert (reason is not None) == blocked


def test_frame_ancestors_self_allows_same_origin():
    import httpx

    from homestart.api.links import _frame_blocked_reason

    headers = httpx.Headers({"Content-Security-Policy": "frame-ancestors 'self'"})
    assert _frame_blocked_reason(headers, "http://192.0.2.5:8000", "http://192.0.2.5:8000") is None
    assert _frame_blocked_reason(headers, "http://192.0.2.5:8000", "http://192.0.2.9:8080") is not None

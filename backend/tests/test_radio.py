import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from homestart.config import load_settings
from homestart.main import create_app
from homestart.services.radio.icy import IcyDemuxer, decode_title

CSRF = {"X-HomeStart": "1"}
BLOCK = 16
TITLE = "StreamTitle='Artist - Čuvar';"


def meta_block(text: str) -> bytes:
    raw = text.encode("utf-8")
    padded = raw + b"\0" * (-len(raw) % 16)
    return bytes([len(padded) // 16]) + padded


class FakeServer:
    """Runs a request handler class on a free local port in a thread."""

    def __init__(self, handler):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class IcySource(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    requests: list[str] = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        IcySource.requests.append(self.path)
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
            return
        if self.path == "/html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html></html>")
            return
        if self.path == "/plain":
            self.send_response(200)
            self.send_header("Content-Type", "audio/aacp")
            self.end_headers()
            try:
                while True:
                    self.wfile.write(b"B" * 100)
                    time.sleep(0.02)
            except OSError:
                return
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("icy-metaint", str(BLOCK))
        self.end_headers()
        try:
            count = 0
            while True:
                self.wfile.write(b"A" * BLOCK)
                # No title for the first blocks, then a title.
                self.wfile.write(meta_block(TITLE) if count >= 3 else b"\0")
                count += 1
                time.sleep(0.02)
        except OSError:
            return


class FakeOpenhab(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    hits: list[str] = []

    def log_message(self, *args):
        pass

    def _send(self, body: bytes, content_type="text/html", status=200, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        FakeOpenhab.hits.append(self.path)
        if self.path.startswith("/basicui/app"):
            self._send(b"<html>Basic UI</html>" + b" " * 3000)
        elif self.path == "/rest/redirect":
            self._send(b"", status=302, extra={"Location": f"http://127.0.0.1:{self.server.server_port}/basicui/app"})
        elif self.path == "/rest/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                for n in range(50):
                    event = f"data: {n}\n\n".encode()
                    self.wfile.write(f"{len(event):x}\r\n".encode() + event + b"\r\n")
                    self.wfile.flush()
                    time.sleep(0.2)
            except OSError:
                return
        elif self.path == "/secret":
            self._send(b"secret")
        else:
            self._send(b"missing", status=404)

    def do_POST(self):
        FakeOpenhab.hits.append(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self._send(body, "text/plain", extra={"X-Seen-Cookie": self.headers.get("Cookie", "")})


@pytest.fixture
def source():
    IcySource.requests = []
    server = FakeServer(IcySource)
    yield server
    server.stop()


@pytest.fixture
def openhab():
    FakeOpenhab.hits = []
    server = FakeServer(FakeOpenhab)
    yield server
    server.stop()


def write_ini(app_dir, radio_section=""):
    (app_dir / "homestart.ini").write_text(f"[database]\nfile = data/test.db\n[mqtt]\nenabled = false\n{radio_section}")


@pytest.fixture
def client(tmp_path):
    write_ini(tmp_path)
    with TestClient(create_app(load_settings(tmp_path))) as test_client:
        yield test_client


@pytest.fixture
def live(tmp_path, openhab):
    """The application on a real local port, for streaming responses (the test client buffers them)."""
    write_ini(tmp_path, f"[radio]\nmax_listeners = 2\nopenhab_url = {openhab.url}\n")
    app = create_app(load_settings(tmp_path))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}", app
    server.should_exit = True
    thread.join(5)


def login_admin(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers=CSRF)
    assert response.status_code == 200


def add_station(base, slug, urls, **extra):
    """Adds a station through the admin API of a running server."""
    with httpx.Client(base_url=base) as http:
        http.post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers=CSRF).raise_for_status()
        http.post(
            "/api/radio/stations",
            json={"slug": slug, "name": slug.title(), "urls": urls, **extra},
            headers=CSRF,
        ).raise_for_status()


def read_stream(url, size):
    got = b""
    with httpx.stream("GET", url, timeout=10) as response:
        assert response.status_code == 200
        for chunk in response.iter_bytes():
            got += chunk
            if len(got) >= size:
                break
        return response.headers, got


# --- ICY ---------------------------------------------------------------------


def test_icy_demuxer_removes_metadata_across_chunk_borders():
    stream = (b"A" * BLOCK + b"\0") + (b"B" * BLOCK + meta_block(TITLE)) + b"C" * BLOCK + b"\0"
    demuxer = IcyDemuxer(BLOCK)
    audio = b"".join(demuxer.feed(stream[i : i + 5]) for i in range(0, len(stream), 5))
    assert audio == b"A" * BLOCK + b"B" * BLOCK + b"C" * BLOCK
    assert demuxer.title == "Artist - Čuvar"


def test_icy_title_decoding():
    assert decode_title("StreamTitle='Ñandú';".encode("latin-1")) == "Ñandú"
    assert decode_title(b"StreamTitle='';") is None
    assert decode_title(b"StreamTitle='a\x07b';") == "ab"
    assert decode_title(b"nothing") is None


# --- station administration ----------------------------------------------------


def test_seven_stations_are_provided_and_listed_for_the_panel(client):
    login_admin(client)
    listed = client.get("/api/radio/stations").json()
    assert [s["slug"] for s in listed][:2] == ["rock-radio-beograd", "radio-s-rock"]
    assert len(listed) == 7
    panel = client.get("/openpanel/stations").json()
    assert panel["openhab_enabled"] is False
    assert "urls" not in panel["stations"][0]


def test_station_admin_crud_and_validation(client):
    login_admin(client)
    body = {"slug": "my-radio", "name": "My radio", "urls": ["http://example.org/s"], "content_type": "audio/aac"}
    created = client.post("/api/radio/stations", json=body, headers=CSRF)
    assert created.status_code == 201
    station_id = created.json()["id"]
    assert client.post("/api/radio/stations", json=body, headers=CSRF).status_code == 409

    for bad in (
        {**body, "slug": "Has Space"},
        {**body, "urls": []},
        {**body, "urls": ["ftp://example.org/x"]},
        {**body, "urls": ["http://user:pw@example.org/x"]},
        {**body, "content_type": "nonsense"},
    ):
        assert client.post("/api/radio/stations", json=bad, headers=CSRF).status_code == 422

    updated = client.put(f"/api/radio/stations/{station_id}", json={**body, "name": "Renamed"}, headers=CSRF)
    assert updated.json()["name"] == "Renamed"

    ids = [s["id"] for s in client.get("/api/radio/stations").json()]
    reordered = client.put("/api/radio/stations/order", json={"ids": ids[::-1]}, headers=CSRF)
    assert [s["id"] for s in reordered.json()] == ids[::-1]
    assert client.put("/api/radio/stations/order", json={"ids": ids[:2]}, headers=CSRF).status_code == 400

    assert client.delete(f"/api/radio/stations/{station_id}", headers=CSRF).status_code == 204
    assert client.delete(f"/api/radio/stations/{station_id}", headers=CSRF).status_code == 404


def test_station_admin_requires_admin(client):
    assert client.get("/api/radio/stations").status_code == 401
    login_admin(client)
    client.post("/api/users", json={"username": "bob", "password": "bobpass", "role": "user"}, headers=CSRF)
    client.post("/api/auth/logout", headers=CSRF)
    client.post("/api/auth/login", json={"username": "bob", "password": "bobpass"}, headers=CSRF)
    assert client.get("/api/radio/stations").status_code == 403


# --- local network access -------------------------------------------------------


def test_panel_is_closed_outside_the_local_network(tmp_path):
    write_ini(tmp_path)
    app = create_app(load_settings(tmp_path))
    with TestClient(app, client=("8.8.8.8", 5000)) as outside, TestClient(app, client=("192.168.1.20", 5000)) as inside:
        for path in ("/openpanel/", "/openpanel/stations", "/openpanel/status"):
            assert outside.get(path).status_code == 403, path
            assert inside.get(path).status_code == 200, path
        assert outside.get("/openpanel/radio/no-such-station").status_code == 403
        assert inside.get("/openpanel/radio/no-such-station").status_code == 404
        assert "Radio panel" in inside.get("/openpanel/").text
        assert inside.get("/openpanel/panel.js").status_code == 200
        assert inside.get("/openpanel/secret.py").status_code == 404

        # A logged-in HomeStart user may use it from anywhere.
        login_admin(outside)
        assert outside.get("/openpanel/stations").status_code == 200
    with TestClient(app, client=("172.16.0.9", 5000)) as other_private:
        assert other_private.get("/openpanel/stations").status_code == 403


def test_forwarded_for_header_is_ignored(tmp_path):
    write_ini(tmp_path)
    with TestClient(create_app(load_settings(tmp_path)), client=("8.8.8.8", 1)) as outside:
        assert outside.get("/openpanel/stations", headers={"X-Forwarded-For": "192.168.1.5"}).status_code == 403


# --- audio relay ------------------------------------------------------------------


def test_stream_strips_metadata_and_reports_title(live, source):
    base, app = live
    add_station(base, "test-icy", [source.url + "/ok"])
    headers, audio = read_stream(base + "/openpanel/radio/test-icy", 800)
    assert headers["content-type"].startswith("audio/mpeg")
    assert headers["cache-control"] == "no-cache, no-store"
    assert "content-length" not in headers
    assert headers.get("content-encoding") == "identity"
    # Only the audio bytes arrived, with no metadata blocks mixed in.
    assert set(audio) == {ord("A")}

    with httpx.stream("GET", base + "/openpanel/radio/test-icy") as response:
        chunks = response.iter_bytes()  # kept referenced: a dropped iterator would close the response
        next(chunks)
        time.sleep(0.4)
        report = httpx.get(base + "/openpanel/status").json()
    station = next(s for s in report["stations"] if s["id"] == "test-icy")
    assert station["title"] == "Artist - Čuvar"
    assert station["listeners"] == 1
    assert report["total_listeners"] == 1


def test_stream_without_metadata_uses_content_type_override(live, source):
    base, app = live
    add_station(base, "plain-one", [source.url + "/plain"], content_type="audio/aac")
    headers, audio = read_stream(base + "/openpanel/radio/plain-one", 500)
    assert headers["content-type"].startswith("audio/aac")
    assert set(audio) == {ord("B")}


def test_redirects_and_second_address_are_followed(live, source):
    base, app = live
    add_station(base, "fallback", ["http://127.0.0.1:1/dead", source.url + "/html", source.url + "/redirect"])
    _, audio = read_stream(base + "/openpanel/radio/fallback", 200)
    assert audio.startswith(b"A")


def test_unreachable_or_non_audio_source_gives_502(live, source):
    base, app = live
    add_station(base, "dead", ["http://127.0.0.1:1/x"])
    add_station(base, "webpage", [source.url + "/html"])
    assert httpx.get(base + "/openpanel/radio/dead", timeout=20).status_code == 502
    assert httpx.get(base + "/openpanel/radio/webpage", timeout=20).status_code == 502
    assert app.state.radio.listener_count() == 0
    assert app.state.radio.streams == {}


def test_unknown_station_is_404(live):
    base, app = live
    assert httpx.get(base + "/openpanel/radio/nope").status_code == 404


def test_listeners_share_one_connection_and_limit_gives_503(live, source):
    base, app = live
    add_station(base, "shared", [source.url + "/ok"])
    add_station(base, "other", [source.url + "/plain"])
    first = httpx.stream("GET", base + "/openpanel/radio/shared")
    second = httpx.stream("GET", base + "/openpanel/radio/shared")
    with first as r1, second as r2:
        chunks = (r1.iter_bytes(), r2.iter_bytes())
        next(chunks[0])
        next(chunks[1])
        assert app.state.radio.listener_count() == 2
        assert IcySource.requests.count("/ok") == 1  # one upstream connection for both
        # max_listeners is 2 in this fixture
        assert httpx.get(base + "/openpanel/radio/other", timeout=10).status_code == 503


def test_source_connection_closes_when_the_last_listener_leaves(live, source):
    base, app = live
    add_station(base, "closing", [source.url + "/ok"])
    with httpx.stream("GET", base + "/openpanel/radio/closing") as response:
        chunks = response.iter_bytes()
        next(chunks)
        assert "closing" in app.state.radio.streams
    for _ in range(50):
        if not app.state.radio.streams:
            break
        time.sleep(0.1)
    assert app.state.radio.streams == {}
    assert app.state.radio.listener_count() == 0


def test_head_request_reports_the_type_without_keeping_a_listener(live, source):
    base, app = live
    add_station(base, "headed", [source.url + "/ok"])
    response = httpx.head(base + "/openpanel/radio/headed", timeout=10)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert app.state.radio.listener_count() == 0


# --- openHAB pass-through -----------------------------------------------------------


def test_openhab_paths_are_forwarded(live, openhab):
    base, app = live
    page = httpx.get(base + "/basicui/app?sitemap=home", headers={"Accept-Encoding": "gzip"})
    assert page.status_code == 200 and "Basic UI" in page.text
    assert "content-security-policy" not in page.headers
    assert "x-frame-options" not in page.headers
    assert page.headers.get("content-encoding") in (None, "identity")
    assert "/basicui/app?sitemap=home" in FakeOpenhab.hits

    redirect = httpx.get(base + "/rest/redirect", follow_redirects=False)
    assert redirect.status_code == 302
    assert redirect.headers["location"] == "/basicui/app"


def test_openhab_unlisted_paths_are_not_forwarded(live, openhab):
    base, app = live
    httpx.get(base + "/secret")
    assert "/secret" not in FakeOpenhab.hits


def test_openhab_post_body_is_forwarded_and_session_cookie_is_not(live):
    base, app = live
    response = httpx.post(
        base + "/rest/items/Light",
        content=b"ON",
        headers={"Cookie": "homestart_session=abc; JSESSIONID=xyz"},
    )
    assert response.content == b"ON"
    assert response.headers["x-seen-cookie"] == "JSESSIONID=xyz"


def test_openhab_live_events_are_not_held_back(live):
    base, app = live
    started = time.monotonic()
    with httpx.stream("GET", base + "/rest/events", headers={"Accept-Encoding": "gzip"}, timeout=10) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        first = next(response.iter_lines())
    assert first == "data: 0"
    assert time.monotonic() - started < 1.0


def test_openhab_is_closed_outside_the_local_network(tmp_path, openhab):
    write_ini(tmp_path, f"[radio]\nopenhab_url = {openhab.url}\n")
    app = create_app(load_settings(tmp_path))
    with TestClient(app, client=("8.8.8.8", 1)) as outside:
        assert outside.get("/basicui/app").status_code == 403
        assert outside.get("/rest/events").status_code == 403
    assert FakeOpenhab.hits == []


def test_openhab_not_reachable_gives_502(tmp_path):
    write_ini(tmp_path, "[radio]\nopenhab_url = http://127.0.0.1:1\n")
    with TestClient(create_app(load_settings(tmp_path)), client=("127.0.0.1", 1)) as inside:
        assert inside.get("/basicui/app").status_code == 502


def test_openhab_tab_is_reported_when_configured(tmp_path, openhab):
    write_ini(tmp_path, f"[radio]\nopenhab_url = {openhab.url}\nopenhab_start = /basicui/app?sitemap=x\n")
    with TestClient(create_app(load_settings(tmp_path)), client=("127.0.0.1", 1)) as inside:
        data = inside.get("/openpanel/stations").json()
        assert data["openhab_enabled"] is True
        assert data["openhab_start"] == "/basicui/app?sitemap=x"


def test_invalid_radio_settings_are_rejected(tmp_path):
    from homestart.config import ConfigError

    for section in (
        "[radio]\nallowed_networks = not-a-network\n",
        "[radio]\nopenhab_url = ftp://x\n",
        "[radio]\nopenhab_paths = /api\n",
        "[radio]\nmax_listeners = 0\n",
    ):
        write_ini(tmp_path, section)
        with pytest.raises(ConfigError):
            load_settings(tmp_path)

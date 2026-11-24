"""Network shares, tested against a fake SMB server that serves a local folder (the real library is not used)."""

import logging
from contextlib import contextmanager
from pathlib import Path

import pytest
from smbprotocol.exceptions import SMBOSError
from test_player import CSRF, FRAME, admin, client, make_mp3, music, scan  # noqa: F401 - fixtures

from homestart.db import SessionLocal
from homestart.models import MusicSource
from homestart.services.player.files import LocationError, check_private_host, parse_network_path

HOST, SHARE, USER, PASSWORD = "192.168.1.50", "Muzika", "tester", "fake-secret-pw"
NETWORK_PATH = rf"\\{HOST}\{SHARE}\Albums"


class FakeEntry:
    def __init__(self, path: Path):
        self._path, self.name = path, path.name

    def is_dir(self):
        return self._path.is_dir()

    def is_symlink(self):
        return self._path.is_symlink()

    def stat(self):
        return self._path.stat()


class FakeSmb:
    """Answers like a share would: checks the user and password, the share and the folder."""

    def __init__(self, base: Path):
        self.base, self.offline, self.calls = base, False, []

    def _resolve(self, path, options):
        if self.offline:
            raise TimeoutError("server does not answer")
        self.calls.append(dict(options))
        parts = [p for p in path.split("\\") if p]
        if parts[0] != HOST:
            raise TimeoutError("unknown server")
        if options.get("username") != USER or options.get("password") != PASSWORD:
            raise SMBOSError(0xC000006D, path)
        if parts[1] != SHARE:
            raise SMBOSError(0xC00000CC, path)
        local = self.base.joinpath(*parts[2:])
        if not local.exists():
            raise SMBOSError(0xC0000034, path)
        return local

    @contextmanager
    def scandir(self, path, **options):
        yield [FakeEntry(p) for p in self._resolve(path, options).iterdir()]

    def open_file(self, path, mode="rb", **options):
        return self._resolve(path, options).open("rb")

    def stat(self, path, **options):
        return self._resolve(path, options).stat()

    def reset_connection_cache(self):
        pass


@pytest.fixture
def smb(monkeypatch, music):  # noqa: F811
    # The share root holds the folder "Albums", which is the music folder of the other tests.
    base = music.parent / "share"
    base.mkdir()
    (base / "Albums").symlink_to(music, target_is_directory=True)
    fake = FakeSmb(base)
    monkeypatch.setattr("homestart.services.player.files.smbclient", fake)
    return fake


def share_body(**changes):
    return {"name": "NAS", "kind": "smb", "network_path": NETWORK_PATH, "username": USER, "password": PASSWORD, **changes}


def add_share(client, **changes):
    response = client.post("/api/config/player/sources", json=share_body(**changes), headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def test_parse_network_path():
    assert parse_network_path(r"\\192.168.1.20\Music\Some Folder") == ("192.168.1.20", "Music", "Some Folder")
    assert parse_network_path("//nas/music/a/b/") == ("nas", "music", "a/b")
    assert parse_network_path("smb://nas/music") == ("nas", "music", "")
    for bad in (r"\\only-server", "", r"\\nas\music\..\other", r"\\na s\music", r"\\nas\mu:sic"):
        with pytest.raises(ValueError):
            parse_network_path(bad)


def test_only_local_network_servers():
    check_private_host("192.168.1.20")
    check_private_host("10.0.0.7")
    check_private_host("127.0.0.1")
    for host in ("8.8.8.8", "1.1.1.1"):
        with pytest.raises(LocationError):
            check_private_host(host)


def test_adding_a_share_keeps_the_password_secret(admin, smb, caplog):
    caplog.set_level(logging.DEBUG)
    shown = add_share(admin)
    assert shown["kind"] == "smb" and shown["network_path"] == NETWORK_PATH
    assert shown["username"] == USER and shown["has_password"] is True and shown["path"] is None
    assert "password" not in shown and PASSWORD not in str(shown)
    assert PASSWORD not in admin.get("/api/config/player/sources").text

    with SessionLocal() as db:
        row = db.get(MusicSource, shown["id"])
        assert (row.host, row.share, row.subpath) == (HOST, SHARE, "Albums")
        for stored in (row.username_enc, row.password_enc):
            assert stored and USER not in stored and PASSWORD not in stored
    scan(admin, shown["id"])
    assert PASSWORD not in caplog.text


def test_share_validation(admin, smb):
    post = lambda body: admin.post("/api/config/player/sources", json=body, headers=CSRF)  # noqa: E731
    assert post(share_body(network_path=r"\\8.8.8.8\music")).status_code == 400
    assert post(share_body(network_path=r"\\only-server")).status_code == 422
    assert post(share_body(network_path=None)).status_code == 422
    assert post({"name": "Local", "kind": "local"}).status_code == 422


def test_scan_and_play_from_a_share(admin, smb, music):
    source = add_share(admin)
    report = scan(admin, source["id"])
    assert report["status"] == "done" and report["added"] == 5
    assert report["new_folders"] == ["Rock Album", "Untagged Band"]
    albums = {a["title"]: a for a in admin.get("/api/player/albums").json()["items"]}
    assert albums["Rock Album"]["tracks"] == 3
    # Everything went over the fake SMB connection with the saved user and password, as NTLM on the default port.
    assert smb.calls and all(c["username"] == USER and c["password"] == PASSWORD for c in smb.calls)
    assert all(c["auth_protocol"] == "ntlm" and c["port"] == 445 for c in smb.calls)

    track = next(t for t in admin.get("/api/player/tracks").json()["items"] if t["title"] == "First")
    data = (music / "Rock Album" / "01 - First.mp3").read_bytes()
    whole = admin.get(f"/player/stream/{track['id']}")
    assert whole.status_code == 200 and whole.content == data
    part = admin.get(f"/player/stream/{track['id']}", headers={"Range": "bytes=20-119"})
    assert part.status_code == 206 and part.content == data[20:120]
    assert part.headers["content-range"] == f"bytes 20-119/{len(data)}"
    assert admin.app.state.player.listeners() == 0


def test_rescan_of_a_share_reports_changes(admin, smb, music):
    source = add_share(admin)
    scan(admin, source["id"])
    make_mp3(music / "Jazz" / "Take Five.mp3", "Take Five", "Quartet", "Time Out", 1, "Jazz")
    (music / "Rock Album" / "02 - Second.mp3").unlink()
    report = scan(admin, source["id"])
    assert report["added_files"] == ["Jazz/Take Five.mp3"] and report["removed_files"] == ["Rock Album/02 - Second.mp3"]
    assert report["new_folders"] == ["Jazz"]


def test_share_that_cannot_be_reached_removes_nothing(admin, smb, caplog):
    caplog.set_level(logging.DEBUG)
    source = add_share(admin)
    scan(admin, source["id"])
    smb.offline = True
    report = scan(admin, source["id"])
    assert report["status"] == "failed" and report["error_message"] == "Cannot reach the server"
    listed = admin.get("/api/config/player/sources").json()[0]
    assert listed["tracks"] == 5 and listed["missing"] == 0
    assert admin.get("/api/player/albums").json()["total"] == 2  # the library stays as it was
    track = admin.get("/api/player/tracks").json()["items"][0]
    stream = admin.get(f"/player/stream/{track['id']}")
    assert stream.status_code == 502 and PASSWORD not in stream.text
    assert PASSWORD not in caplog.text


def test_wrong_password_is_reported_clearly(admin, smb):
    source = add_share(admin, password="not-the-password")
    report = scan(admin, source["id"])
    assert report["status"] == "failed" and report["error_message"] == "Wrong user name or password"
    assert "not-the-password" not in str(report)


def test_connection_test(admin, smb):
    post = lambda body: admin.post("/api/config/player/sources/test", json=body, headers=CSRF).json()  # noqa: E731
    ok = post(share_body())
    assert ok["ok"] is True and ok["tracks"] == 5 and "5 music files" in ok["message"]
    assert post(share_body(password="wrong")) == {"ok": False, "message": "Wrong user name or password", "tracks": None}
    assert post(share_body(network_path=rf"\\{HOST}\Other"))["message"] == "The share does not exist on the server"
    assert post(share_body(network_path=rf"\\{HOST}\{SHARE}\Nope"))["message"] == "The folder does not exist on the share"
    assert post(share_body(network_path=r"\\8.8.8.8\music"))["message"] == "Only servers of the local network are allowed"
    smb.offline = True
    assert post(share_body())["message"] == "Cannot reach the server"
    smb.offline = False

    # Nothing was saved by testing, and the saved password is used when none is typed.
    assert admin.get("/api/config/player/sources").json() == []
    saved = add_share(admin)
    assert post(share_body(password=None, source_id=saved["id"]))["ok"] is True
    assert post(share_body(password=None))["ok"] is False


def test_local_connection_test(admin, music, tmp_path):
    post = lambda body: admin.post("/api/config/player/sources/test", json=body, headers=CSRF).json()  # noqa: E731
    assert post({"name": "x", "path": str(music)})["tracks"] == 5
    assert post({"name": "x", "path": str(tmp_path / "nope")})["ok"] is False


def test_editing_a_share(admin, smb):
    source = add_share(admin)
    url = f"/api/config/player/sources/{source['id']}"
    # No password typed: the saved one stays.
    assert admin.put(url, json=share_body(password=None, name="Renamed"), headers=CSRF).status_code == 200
    assert scan(admin, source["id"])["status"] == "done"
    # A new password replaces it, and a wrong one is used from then on.
    admin.put(url, json=share_body(password="changed-pw"), headers=CSRF)
    assert scan(admin, source["id"])["error_message"] == "Wrong user name or password"
    admin.put(url, json=share_body(password=PASSWORD), headers=CSRF)
    assert scan(admin, source["id"])["status"] == "done"
    # The kind cannot change.
    assert admin.put(url, json={"name": "x", "kind": "local", "path": "/tmp"}, headers=CSRF).status_code == 400
    # Without a user name the share is read as a guest and the saved password is dropped.
    shown = admin.put(url, json=share_body(username=None, password=None), headers=CSRF).json()
    assert shown["username"] is None and shown["has_password"] is False
    smb.calls.clear()
    assert scan(admin, source["id"])["status"] == "failed"
    assert smb.calls and smb.calls[0]["username"] == "Guest" and smb.calls[0]["password"] == ""


def test_deleting_a_share(admin, smb, music):
    source = add_share(admin)
    scan(admin, source["id"])
    assert admin.delete(f"/api/config/player/sources/{source['id']}", headers=CSRF).status_code == 204
    assert admin.get("/api/player/albums").json()["total"] == 0
    assert (music / "Rock Album" / "01 - First.mp3").exists()

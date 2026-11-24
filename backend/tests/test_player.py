import os

import pytest
from fastapi.testclient import TestClient
from mutagen.id3 import ID3, TALB, TCON, TIT2, TPE1, TPE2, TRCK

from homestart.config import load_settings
from homestart.main import create_app
from homestart.services.player.tags import fold, repair

CSRF = {"X-HomeStart": "1"}
# One MPEG layer 3 frame (128 kbit/s, 44.1 kHz), enough for the file to be recognised as audio.
FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413


def make_mp3(path, title=None, artist=None, album=None, track=None, genre=None, album_artist=None, raw_latin1=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(FRAME * 20)
    frames = [
        TIT2(encoding=0, text=title) if title else None,
        TPE1(encoding=0, text=artist) if artist else None,
        TALB(encoding=0, text=album) if album else None,
        TRCK(encoding=0, text=str(track)) if track else None,
        TCON(encoding=0, text=genre) if genre else None,
        TPE2(encoding=0, text=album_artist) if album_artist else None,
    ]
    frames = [f for f in frames if f is not None]
    if frames:
        tags = ID3()
        for frame in frames:
            tags.add(frame)
        tags.save(path, v2_version=3)


@pytest.fixture
def music(tmp_path):
    root = tmp_path / "music"
    make_mp3(root / "Rock Album" / "01 - First.mp3", "First", "The Band", "Rock Album", 1, "Rock")
    make_mp3(root / "Rock Album" / "02 - Second.mp3", "Second", "The Band", "Rock Album", 2, "rock")
    # Text in Windows-1250 (the byte 0x8a is "Š") declared as Latin-1, as old tags often are.
    make_mp3(root / "Rock Album" / "03 - Third.mp3", b"\x8atogod".decode("latin-1"), "The Band", "Rock Album", 3, "Rock")
    make_mp3(root / "Untagged Band" / "Untagged Band - 01 - Nameless.mp3")
    make_mp3(root / "Untagged Band" / "Untagged Band - 02 - Nameless Two.MP3")
    (root / "Untagged Band" / "notes.txt").write_text("not music")
    return root


@pytest.fixture
def client(tmp_path):
    (tmp_path / "homestart.ini").write_text("[database]\nfile = data/test.db\n[mqtt]\nenabled = false\n[player]\nmetadata_online = false\n")
    app = create_app(load_settings(tmp_path))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin(client):
    assert client.post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers=CSRF).status_code == 200
    return client


def add_source(client, path, name="Music"):
    response = client.post("/api/config/player/sources", json={"name": name, "path": str(path)}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def scan(client, source_id):
    response = client.post(f"/api/config/player/sources/{source_id}/scan", headers=CSRF)
    assert response.status_code == 202, response.text
    client.app.state.player_scans.wait()
    return client.get(f"/api/config/player/scans/{response.json()['scan_id']}").json()


# --- tags ---------------------------------------------------------------------


def test_fold_removes_accents_and_case():
    assert fold("Što ĐURĐEVDAN Ćevap") == "sto durdevdan cevap"


def test_repair_legacy_encoding():
    assert repair("\x8atogod", "cp1250") == "Štogod"
    assert repair("Štogod".encode().decode("latin-1"), "cp1250") == "Štogod"  # UTF-8 stored as Latin-1
    assert repair("plain", "cp1250") == "plain"
    assert repair("Štogod", "cp1250") == "Štogod"  # already Unicode


# --- access ---------------------------------------------------------------------


def test_library_requires_login(client):
    assert client.get("/api/player/albums").status_code == 401
    assert client.get("/api/config/player/sources").status_code == 401


def test_only_administrators_manage_locations(client, music):
    admin_login = client.post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers=CSRF)
    assert admin_login.status_code == 200
    client.post("/api/users", json={"username": "ana", "password": "password-123", "role": "user"}, headers=CSRF)
    client.post("/api/auth/logout", headers=CSRF)
    client.post("/api/auth/login", json={"username": "ana", "password": "password-123"}, headers=CSRF)
    assert client.get("/api/config/player/sources").status_code == 403
    assert client.post("/api/config/player/sources", json={"name": "x", "path": str(music)}, headers=CSRF).status_code == 403
    assert client.get("/api/player/albums").status_code == 200


# --- locations ------------------------------------------------------------------


def test_source_validation(admin, music, tmp_path):
    post = lambda body: admin.post("/api/config/player/sources", json=body, headers=CSRF)  # noqa: E731
    assert post({"name": "Rel", "path": "music"}).status_code == 400
    assert post({"name": "Missing", "path": str(tmp_path / "nope")}).status_code == 400
    assert post({"name": "A file", "path": str(music / "notes")}).status_code == 400
    assert post({"name": "SMB", "kind": "smb", "path": "x"}).status_code == 422
    add_source(admin, music)
    assert post({"name": "Music", "path": str(music)}).status_code == 409


# --- scanning -------------------------------------------------------------------


def test_first_scan_builds_the_library(admin, music):
    source = add_source(admin, music)
    report = scan(admin, source["id"])
    assert report["status"] == "done"
    assert report["added"] == 5 and report["changed"] == 0 and report["removed"] == 0
    assert report["new_folders"] == ["Rock Album", "Untagged Band"]
    assert "Untagged Band/notes.txt" not in report["added_files"]

    albums = admin.get("/api/player/albums").json()
    assert albums["total"] == 2
    by_title = {a["title"]: a for a in albums["items"]}
    assert by_title["Rock Album"]["artist"] == "The Band" and by_title["Rock Album"]["tracks"] == 3
    # No album tag: the folder is the album, and the artist comes from the file names.
    assert by_title["Untagged Band"]["artist"] == "Untagged Band" and by_title["Untagged Band"]["tracks"] == 2

    detail = admin.get(f"/api/player/albums/{by_title['Rock Album']['id']}").json()
    assert [t["title"] for t in detail["tracks"]] == ["First", "Second", "Štogod"]
    assert [t["track_no"] for t in detail["tracks"]] == [1, 2, 3]

    untagged = admin.get(f"/api/player/albums/{by_title['Untagged Band']['id']}").json()["tracks"]
    assert [(t["track_no"], t["title"]) for t in untagged] == [(1, "Nameless"), (2, "Nameless Two")]

    sources = admin.get("/api/config/player/sources").json()
    assert sources[0]["tracks"] == 5 and sources[0]["last_scan_status"] == "done"


def test_genres_ignore_case(admin, music):
    scan(admin, add_source(admin, music)["id"])
    genres = admin.get("/api/player/genres").json()
    assert [(g["name"], g["tracks"]) for g in genres] == [("Rock", 3), (None, 2)]
    assert admin.get("/api/player/tracks", params={"genre": "ROCK"}).json()["total"] == 3
    assert admin.get("/api/player/tracks", params={"no_genre": "true"}).json()["total"] == 2
    assert admin.get("/api/player/albums", params={"genre": "rock"}).json()["total"] == 1


def test_search_ignores_case_and_accents(admin, music):
    scan(admin, add_source(admin, music)["id"])
    assert admin.get("/api/player/tracks", params={"q": "STOGOD"}).json()["total"] == 1
    assert admin.get("/api/player/tracks", params={"q": "štogod band"}).json()["total"] == 1
    assert admin.get("/api/player/tracks", params={"q": "100%"}).json()["total"] == 0
    assert admin.get("/api/player/albums", params={"q": "untagged"}).json()["total"] == 1


def test_browse_folders(admin, music):
    source = add_source(admin, music)
    scan(admin, source["id"])
    assert admin.get("/api/player/locations").json() == [{"id": source["id"], "name": "Music", "tracks": 5}]
    root = admin.get("/api/player/folders", params={"source_id": source["id"]}).json()
    assert [(f["name"], f["tracks"]) for f in root["folders"]] == [("Rock Album", 3), ("Untagged Band", 2)]
    assert root["tracks"] == []
    inner = admin.get("/api/player/folders", params={"source_id": source["id"], "path": "Rock Album"}).json()
    assert inner["folders"] == [] and len(inner["tracks"]) == 3
    assert admin.get("/api/player/folders", params={"source_id": source["id"], "path": "Nope"}).status_code == 404
    assert admin.get("/api/player/folders", params={"source_id": source["id"], "path": "../.."}).status_code == 404


def test_nested_folders_and_track_in_root(admin, music):
    make_mp3(music / "Rock Album" / "Live" / "Night" / "A.mp3", "Night", "The Band", "Live", 1)
    make_mp3(music / "Loose.mp3", "Loose", "Someone", "Singles")
    source = add_source(admin, music)
    report = scan(admin, source["id"])
    assert "Rock Album/Live" in report["new_folders"] and "Rock Album/Live/Night" in report["new_folders"]
    root = admin.get("/api/player/folders", params={"source_id": source["id"]}).json()
    assert [t["title"] for t in root["tracks"]] == ["Loose"]
    rock = admin.get("/api/player/folders", params={"source_id": source["id"], "path": "Rock Album"}).json()
    assert [(f["name"], f["tracks"]) for f in rock["folders"]] == [("Live", 1)]


def test_rescan_reports_what_changed(admin, music):
    source = add_source(admin, music)
    scan(admin, source["id"])
    again = scan(admin, source["id"])
    assert (again["added"], again["changed"], again["removed"]) == (0, 0, 0)
    assert again["new_folders"] == [] and again["removed_folders"] == []

    make_mp3(music / "Rock Album" / "04 - Fourth.mp3", "Fourth", "The Band", "Rock Album", 4, "Rock")
    make_mp3(music / "Jazz" / "Take Five.mp3", "Take Five", "Quartet", "Time Out", 1, "Jazz")
    (music / "Rock Album" / "01 - First.mp3").write_bytes(FRAME * 30)  # changed, tags gone
    for name in ("Nameless.mp3", "Nameless Two.MP3"):
        (music / "Untagged Band" / f"Untagged Band - {'01' if name == 'Nameless.mp3' else '02'} - {name}").unlink()
    (music / "Untagged Band" / "notes.txt").unlink()
    (music / "Untagged Band").rmdir()

    report = scan(admin, source["id"])
    assert report["status"] == "done"
    assert sorted(report["added_files"]) == ["Jazz/Take Five.mp3", "Rock Album/04 - Fourth.mp3"]
    assert report["changed_files"] == ["Rock Album/01 - First.mp3"]
    assert sorted(report["removed_files"]) == [
        "Untagged Band/Untagged Band - 01 - Nameless.mp3",
        "Untagged Band/Untagged Band - 02 - Nameless Two.MP3",
    ]
    assert report["new_folders"] == ["Jazz"] and report["removed_folders"] == ["Untagged Band"]

    history = admin.get(f"/api/config/player/sources/{source['id']}/scans").json()
    assert [s["added"] for s in history] == [2, 0, 5]
    assert history[0]["started_by"] == "admin"

    # Removed files drop out of the listings but stay in the database, marked as missing.
    sources = admin.get("/api/config/player/sources").json()
    assert sources[0]["tracks"] == 5 and sources[0]["missing"] == 2
    assert admin.get("/api/player/tracks", params={"q": "nameless"}).json()["total"] == 0
    assert {a["title"] for a in admin.get("/api/player/albums").json()["items"]} == {"Rock Album", "Time Out"}

    assert admin.post(f"/api/config/player/sources/{source['id']}/remove-missing", headers=CSRF).json() == {"removed": 2}
    assert admin.get("/api/config/player/sources").json()[0]["missing"] == 0
    titles = {a["title"] for a in admin.get("/api/player/albums").json()["items"]}
    assert "Untagged Band" not in titles


def test_file_that_comes_back_is_added_again(admin, music):
    source = add_source(admin, music)
    scan(admin, source["id"])
    gone = music / "Rock Album" / "02 - Second.mp3"
    data = gone.read_bytes()
    gone.unlink()
    assert scan(admin, source["id"])["removed"] == 1
    gone.write_bytes(data)
    report = scan(admin, source["id"])
    assert report["added_files"] == ["Rock Album/02 - Second.mp3"]
    assert admin.get("/api/config/player/sources").json()[0]["missing"] == 0


def test_unreachable_location_removes_nothing(admin, music, tmp_path):
    source = add_source(admin, music)
    scan(admin, source["id"])
    moved = tmp_path / "moved"
    os.rename(music, moved)
    report = scan(admin, source["id"])
    assert report["status"] == "failed" and "folder" in report["error_message"].lower()
    sources = admin.get("/api/config/player/sources").json()
    assert sources[0]["tracks"] == 5 and sources[0]["missing"] == 0 and sources[0]["last_scan_status"] == "failed"


def test_disabled_location_is_hidden_and_not_scanned(admin, music):
    source = add_source(admin, music)
    scan(admin, source["id"])
    body = {"name": "Music", "path": str(music), "enabled": False}
    assert admin.put(f"/api/config/player/sources/{source['id']}", json=body, headers=CSRF).status_code == 200
    assert admin.get("/api/player/albums").json()["total"] == 0
    assert admin.get("/api/player/locations").json() == []
    assert admin.post(f"/api/config/player/sources/{source['id']}/scan", headers=CSRF).status_code == 400
    assert admin.post("/api/config/player/scan", headers=CSRF).status_code == 400


def test_deleting_a_location_keeps_the_files(admin, music):
    source = add_source(admin, music)
    scan(admin, source["id"])
    assert admin.delete(f"/api/config/player/sources/{source['id']}", headers=CSRF).status_code == 204
    assert admin.get("/api/player/albums").json()["total"] == 0
    assert (music / "Rock Album" / "01 - First.mp3").exists()


def test_scan_all_and_status(admin, music, tmp_path):
    other = tmp_path / "other"
    make_mp3(other / "Song.mp3", "Song", "Singer", "Record")
    add_source(admin, music, "Music")
    add_source(admin, other, "Other")
    response = admin.post("/api/config/player/scan", headers=CSRF)
    assert response.status_code == 202 and response.json()["sources"] == 2
    admin.app.state.player_scans.wait()
    assert admin.get("/api/config/player/status").json() == {"scanning": False, "scan_id": None}
    assert admin.get("/api/player/albums").json()["total"] == 3
    assert admin.post("/api/config/player/scan/cancel", headers=CSRF).status_code == 409


def test_symlink_leaving_the_location_is_skipped(admin, music, tmp_path):
    outside = tmp_path / "outside"
    make_mp3(outside / "Secret.mp3", "Secret", "Nobody", "Hidden")
    os.symlink(outside / "Secret.mp3", music / "Rock Album" / "link.mp3")
    os.symlink(outside, music / "linked-folder")
    report = scan(admin, add_source(admin, music)["id"])
    assert report["added"] == 5
    assert admin.get("/api/player/tracks", params={"q": "secret"}).json()["total"] == 0


def test_scan_survives_a_broken_file(admin, music):
    (music / "Rock Album" / "broken.flac").write_bytes(b"not audio at all")
    report = scan(admin, add_source(admin, music)["id"])
    assert report["status"] == "done" and report["added"] == 6
    broken = admin.get("/api/player/tracks", params={"q": "broken"}).json()["items"]
    assert broken and broken[0]["title"] == "broken"

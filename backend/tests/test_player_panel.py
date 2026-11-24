"""The player on the openpanel: no login, local network only, only what an old tablet can play."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_player import CSRF, FRAME, add_source, make_mp3, scan  # noqa: F401

from homestart.config import load_settings
from homestart.main import create_app

PANEL = "/openpanel/player"
CLIENT = "tablet-0001"
STATIC = Path(__file__).resolve().parents[1] / "homestart" / "static" / "openpanel"


@pytest.fixture
def world(tmp_path):
    """An app with a library, an administrator's client, and a tablet inside and a stranger outside the local network."""
    (tmp_path / "homestart.ini").write_text("[database]\nfile = data/test.db\n[mqtt]\nenabled = false\n[player]\nmetadata_online = false\n")
    music = tmp_path / "music"
    make_mp3(music / "Rock Album" / "01 - First.mp3", "First", "The Band", "Rock Album", 1, "Rock")
    make_mp3(music / "Rock Album" / "02 - Second.mp3", "Second", "The Band", "Rock Album", 2, "Rock")
    (music / "Rock Album" / "03 - Loud.flac").write_bytes(b"fLaC" + b"\0" * 100)  # a type an old tablet cannot play
    make_mp3(music / "Untagged" / "Untagged - 01 - Nameless.mp3")
    app = create_app(load_settings(tmp_path))
    with (
        TestClient(app) as admin,
        TestClient(app, client=("192.168.1.20", 5000)) as tablet,
        TestClient(app, client=("8.8.8.8", 5000)) as stranger,
    ):
        admin.post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers=CSRF)
        source = add_source(admin, music)
        scan(admin, source["id"])
        tracks = {t["title"]: t for t in admin.get("/api/player/tracks", params={"limit": 100}).json()["items"]}
        albums = {a["title"]: a for a in admin.get("/api/player/albums").json()["items"]}
        yield {"admin": admin, "tablet": tablet, "stranger": stranger, "source": source, "tracks": tracks, "albums": albums, "music": music}


def command(client, action, **fields):
    response = client.post(f"{PANEL}/session/command", json={"client_id": CLIENT, "action": action, **fields}, headers=CSRF)
    assert response.status_code == 200, response.text
    return response.json()


def titles(state):
    return [t["title"] for t in state["queue"]]


# --- who may come in -------------------------------------------------------------------


def test_only_the_local_network_gets_in(world):
    assert world["tablet"].get(f"{PANEL}/albums").status_code == 200
    for path in ("/albums", "/tracks", "/genres", "/locations", "/content", "/playlists", f"/session?client_id={CLIENT}", "/stream/1"):
        assert world["stranger"].get(PANEL + path).status_code == 403, path
    assert world["stranger"].post(f"{PANEL}/session/command", json={"client_id": CLIENT, "action": "stop"}, headers=CSRF).status_code == 403
    # A logged-in user is let in from anywhere.
    world["stranger"].post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers=CSRF)
    assert world["stranger"].get(f"{PANEL}/albums").status_code == 200


def test_forwarded_for_is_ignored(world):
    response = world["stranger"].get(f"{PANEL}/albums", headers={"X-Forwarded-For": "192.168.1.20"})
    assert response.status_code == 403


# --- the library -------------------------------------------------------------------------


def test_tablet_sees_only_playable_formats(world):
    tablet, admin = world["tablet"], world["admin"]
    assert admin.get("/api/player/tracks").json()["total"] == 4  # the app shows everything
    shown = tablet.get(f"{PANEL}/tracks").json()
    assert shown["total"] == 3 and "Loud" not in titles({"queue": shown["items"]})
    assert tablet.get(f"{PANEL}/albums", params={"q": "loud"}).json()["total"] == 0
    rock = next(a for a in tablet.get(f"{PANEL}/albums").json()["items"] if a["title"] == "Rock Album")
    assert rock["tracks"] == 2
    detail = tablet.get(f"{PANEL}/albums/{rock['id']}").json()
    assert titles({"queue": detail["tracks"]}) == ["First", "Second"]
    # The format limit belongs to the tablet's requests only.
    assert admin.get("/api/player/tracks").json()["total"] == 4
    assert [g["tracks"] for g in tablet.get(f"{PANEL}/genres").json()][0] <= 3


def test_browsing_by_search_genre_and_folder(world):
    tablet, source = world["tablet"], world["source"]
    assert tablet.get(f"{PANEL}/tracks", params={"q": "FIRST band"}).json()["total"] == 1
    assert tablet.get(f"{PANEL}/tracks", params={"genre": "rock"}).json()["total"] == 2
    locations = tablet.get(f"{PANEL}/locations").json()
    assert locations == [{"id": source["id"], "name": "Music", "tracks": 3}] or locations[0]["name"] == "Music"
    root = tablet.get(f"{PANEL}/folders", params={"source_id": source["id"]}).json()
    assert [(f["name"], f["tracks"]) for f in root["folders"]] == [("Rock Album", 2), ("Untagged", 1)]
    inner = tablet.get(f"{PANEL}/folders", params={"source_id": source["id"], "path": "Rock Album"}).json()
    assert titles({"queue": inner["tracks"]}) == ["First", "Second"]
    assert "path" not in str(locations).lower().replace("tracks", "")  # no paths of the server


def test_covers(world):
    from test_player_metadata import embed, picture  # noqa: F401

    embed(world["music"] / "Rock Album" / "01 - First.mp3", picture())
    world["admin"].post(f"/api/config/player/sources/{world['source']['id']}/scan", headers=CSRF)
    world["admin"].app.state.player_scans.wait()
    world["admin"].app.state.player_metadata.wait()
    album = next(a for a in world["tablet"].get(f"{PANEL}/albums").json()["items"] if a["title"] == "Rock Album")
    assert album["has_cover"] is True
    response = world["tablet"].get(f"{PANEL}/cover/{album['id']}", params={"size": 96})
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    assert world["stranger"].get(f"{PANEL}/cover/{album['id']}").status_code == 403


# --- what the administrator offers --------------------------------------------------------------


def test_content_for_the_tablet(world):
    admin, tablet, tracks, albums = world["admin"], world["tablet"], world["tracks"], world["albums"]
    panel = admin.post("/api/player/playlists", json={"name": "Evening", "panel": True}, headers=CSRF).json()
    admin.post(f"/api/player/playlists/{panel['id']}/tracks", json={"album_id": albums["Rock Album"]["id"]}, headers=CSRF)
    private = admin.post("/api/player/playlists", json={"name": "Private"}, headers=CSRF).json()
    put = lambda **body: admin.post("/api/config/player/panel/items", json=body, headers=CSRF)  # noqa: E731
    put(section="favorites", kind="track", ref=str(tracks["First"]["id"]), title="Favourite")
    put(section="favorites", kind="track", ref=str(tracks["Loud"]["id"]))
    put(section="suggestions", kind="album", ref=str(albums["Rock Album"]["id"]))
    put(section="suggestions", kind="folder", ref=f"{world['source']['id']}:Untagged")
    put(section="suggestions", kind="playlist", ref=str(panel["id"]))

    content = tablet.get(f"{PANEL}/content").json()
    assert [(i["title"], i["available"]) for i in content["favorites"]] == [("Favourite", True), (None, False)]  # the flac cannot be played here
    assert [i["selector"] for i in content["suggestions"]] == [
        {"album_id": albums["Rock Album"]["id"]},
        {"source_id": world["source"]["id"], "path": "Untagged"},
        {"playlist_id": panel["id"]},
    ]
    assert [p["name"] for p in content["playlists"]] == ["Evening"]
    assert [p["name"] for p in tablet.get(f"{PANEL}/playlists").json()] == ["Evening"]
    detail = tablet.get(f"{PANEL}/playlists/{panel['id']}").json()
    # The flac is on the list but marked as not playable here, which is how the page knows to leave it out.
    assert [(t["title"], t["available"]) for t in detail["tracks"]] == [("First", True), ("Second", True), ("Loud", False)]
    assert detail["playlist"]["playable"] == 2
    # Somebody's own playlist does not exist for the tablet.
    assert tablet.get(f"{PANEL}/playlists/{private['id']}").status_code == 404
    denied = tablet.post(f"{PANEL}/session/command", json={"client_id": CLIENT, "action": "play", "playlist_id": private["id"]}, headers=CSRF)
    assert denied.status_code == 404

    # The selector of an item is what the player is given.
    for item in content["suggestions"]:
        assert titles(command(tablet, "play", **item["selector"]))


# --- playing -----------------------------------------------------------------------------------


def test_the_tablet_has_its_own_session(world):
    tablet, admin = world["tablet"], world["admin"]
    state = command(tablet, "play", album_id=world["albums"]["Rock Album"]["id"])
    assert state["status"] == "playing" and titles(state) == ["First", "Second"]
    assert titles(command(tablet, "next")) == ["First", "Second"] and tablet.get(f"{PANEL}/session", params={"client_id": CLIENT}).json()["index"] == 1
    assert command(tablet, "shuffle", on=True)["shuffle"] is True
    assert command(tablet, "stop")["status"] == "stopped"
    # Neither the administrator's session nor another tablet's is touched.
    assert admin.get("/api/player/session", params={"client_id": CLIENT}).json()["queue"] == []
    other = tablet.get(f"{PANEL}/session", params={"client_id": "tablet-0002"}).json()
    assert other["queue"] == []


def test_the_tablet_cannot_queue_what_it_cannot_play(world):
    flac = world["tracks"]["Loud"]
    response = world["tablet"].post(f"{PANEL}/session/command", json={"client_id": CLIENT, "action": "play", "track_id": flac["id"]}, headers=CSRF)
    assert response.status_code == 404


def test_commands_need_the_header(world):
    tablet = world["tablet"]
    assert tablet.post(f"{PANEL}/session/command", json={"client_id": CLIENT, "action": "stop"}).status_code == 403
    assert tablet.post(f"{PANEL}/session/command", json={"client_id": "x", "action": "stop"}, headers=CSRF).status_code == 422
    assert tablet.get(f"{PANEL}/session", params={"client_id": "x"}).status_code == 422


def test_streaming_to_the_tablet(world):
    tablet = world["tablet"]
    first = world["tracks"]["First"]
    data = (world["music"] / "Rock Album" / "01 - First.mp3").read_bytes()
    whole = tablet.get(f"{PANEL}/stream/{first['id']}", params={"sid": CLIENT})
    assert whole.status_code == 200 and whole.content == data and whole.headers["content-type"] == "audio/mpeg"
    assert whole.headers["accept-ranges"] == "bytes"
    part = tablet.get(f"{PANEL}/stream/{first['id']}", params={"sid": CLIENT}, headers={"Range": "bytes=10-59"})
    assert part.status_code == 206 and part.content == data[10:60]
    assert tablet.get(f"{PANEL}/stream/{world['tracks']['Loud']['id']}").status_code == 404
    assert tablet.get(f"{PANEL}/stream/99999").status_code == 404
    assert world["stranger"].get(f"{PANEL}/stream/{first['id']}").status_code == 403
    assert world["admin"].app.state.player.listeners() == 0


def test_the_listener_limit_covers_tablets(world):
    hub = world["admin"].app.state.player
    hub.max_listeners = 1
    hub.acquire_stream("panel:somebody-else")
    first = world["tracks"]["First"]
    assert world["tablet"].get(f"{PANEL}/stream/{first['id']}", params={"sid": CLIENT}).status_code == 503


# --- the page -----------------------------------------------------------------------------------


def test_page_and_script_are_served(world):
    tablet = world["tablet"]
    page = tablet.get("/openpanel/")
    assert page.status_code == 200 and "music.js" in page.text and 'id="tab-music"' in page.text
    script = tablet.get("/openpanel/music.js")
    assert script.status_code == 200 and "javascript" in script.headers["content-type"]
    assert world["stranger"].get("/openpanel/music.js").status_code == 403


FORBIDDEN_IN_ES5 = [
    (r"=>", "arrow function"),
    (r"\blet\b", "let"),
    (r"\bconst\b", "const"),
    (r"`", "template literal"),
    (r"\bfetch\s*\(", "fetch"),
    (r"\bPromise\b", "Promise"),
    (r"\basync\b|\bawait\b", "async/await"),
    (r"\.(includes|startsWith|endsWith|find|findIndex|padStart|repeat)\s*\(", "ES6 method"),
    (r"\bObject\.(assign|entries|values)\b", "ES6 Object method"),
    (r"\bclass\s+\w+", "class"),
    (r"\.\.\.", "spread"),
    (r"\bnew (Map|Set|WeakMap)\b|\bSymbol\b", "ES6 collection"),
]


@pytest.mark.parametrize("name", ["panel.js", "music.js"])
def test_scripts_stay_plain_es5(name):
    """Safari on iOS 9 cannot run anything newer; this keeps a modern habit from slipping in."""
    source = (STATIC / name).read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    code = re.sub(r"(?m)^\s*//.*$", "", code)
    code = re.sub(r"(?<![:'\"\\])//[^\n]*", "", code)
    for pattern, label in FORBIDDEN_IN_ES5:
        assert not re.search(pattern, code), f"{name} uses {label}"

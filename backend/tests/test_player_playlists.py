import pytest
from test_player import CSRF, add_source, admin, client, make_mp3, music, scan  # noqa: F401 - fixtures

CLIENT = "client-0001"
PASSWORD = "password-123"


@pytest.fixture
def library(admin, music):  # noqa: F811
    source = add_source(admin, music)
    scan(admin, source["id"])
    tracks = {t["title"]: t for t in admin.get("/api/player/tracks", params={"limit": 100}).json()["items"]}
    albums = {a["title"]: a for a in admin.get("/api/player/albums").json()["items"]}
    return {"source": source, "tracks": tracks, "albums": albums, "music": music}


def login(client, username, password=PASSWORD):
    client.post("/api/auth/logout", headers=CSRF)
    assert client.post("/api/auth/login", json={"username": username, "password": password}, headers=CSRF).status_code == 200


def make_user(client, name):
    client.post("/api/users", json={"username": name, "password": PASSWORD, "role": "user"}, headers=CSRF)


def create(client, name="Mine", panel=False):
    response = client.post("/api/player/playlists", json={"name": name, "panel": panel}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def add(client, playlist, **selection):
    response = client.post(f"/api/player/playlists/{playlist['id']}/tracks", json=selection, headers=CSRF)
    assert response.status_code == 200, response.text
    return response.json()


def titles(detail):
    return [t["title"] for t in detail["tracks"]]


# --- own playlists -------------------------------------------------------------------


def test_create_rename_delete(admin, library):
    playlist = create(admin, "  Road trip  ")
    assert playlist["name"] == "Road trip" and playlist["editable"] and not playlist["panel"] and playlist["tracks"] == 0
    renamed = admin.put(f"/api/player/playlists/{playlist['id']}", json={"name": "Night"}, headers=CSRF).json()
    assert renamed["name"] == "Night"
    assert [p["name"] for p in admin.get("/api/player/playlists").json()] == ["Night"]
    assert admin.delete(f"/api/player/playlists/{playlist['id']}", headers=CSRF).status_code == 204
    assert admin.get(f"/api/player/playlists/{playlist['id']}").status_code == 404
    assert admin.post("/api/player/playlists", json={"name": "   "}, headers=CSRF).status_code == 422


def test_building_a_playlist(admin, library):
    playlist = create(admin)
    tracks = library["tracks"]
    detail = add(admin, playlist, track_id=tracks["Second"]["id"])
    assert titles(detail) == ["Second"]
    detail = add(admin, playlist, album_id=library["albums"]["Rock Album"]["id"])
    assert titles(detail) == ["Second", "First", "Second", "Štogod"]  # a track may be on the list twice
    detail = add(admin, playlist, source_id=library["source"]["id"], path="Untagged Band")
    assert titles(detail)[-2:] == ["Nameless", "Nameless Two"]
    assert detail["playlist"]["tracks"] == 6 and detail["playlist"]["playable"] == 6
    assert detail["playlist"]["duration_s"] > 0
    detail = add(admin, playlist, track_ids=[tracks["Štogod"]["id"], 99999])
    assert titles(detail)[-1] == "Štogod" and len(detail["tracks"]) == 7
    assert all(t["available"] for t in detail["tracks"])
    post = lambda body: admin.post(f"/api/player/playlists/{playlist['id']}/tracks", json=body, headers=CSRF)  # noqa: E731
    assert post({}).status_code == 400
    assert post({"album_id": 99999}).status_code == 404


def test_remove_and_reorder(admin, library):
    playlist = create(admin)
    detail = add(admin, playlist, album_id=library["albums"]["Rock Album"]["id"])
    first, second, third = (t["entry_id"] for t in detail["tracks"])
    url = f"/api/player/playlists/{playlist['id']}"
    reordered = admin.put(f"{url}/order", json={"entry_ids": [third, first, second]}, headers=CSRF).json()
    assert titles(reordered) == ["Štogod", "First", "Second"]
    assert admin.put(f"{url}/order", json={"entry_ids": [first, second]}, headers=CSRF).status_code == 400
    assert admin.put(f"{url}/order", json={"entry_ids": [first, second, third, 999]}, headers=CSRF).status_code == 400
    removed = admin.delete(f"{url}/tracks/{first}", headers=CSRF).json()
    assert titles(removed) == ["Štogod", "Second"]
    assert admin.delete(f"{url}/tracks/{first}", headers=CSRF).status_code == 404
    again = add(admin, playlist, track_id=library["tracks"]["First"]["id"])
    assert titles(again) == ["Štogod", "Second", "First"]  # new entries go to the end


def test_size_limits(admin, library, monkeypatch):
    monkeypatch.setattr("homestart.api.player_playlists.MAX_PLAYLIST_TRACKS", 3)
    monkeypatch.setattr("homestart.api.player_playlists.MAX_PLAYLISTS_PER_USER", 2)
    playlist = create(admin)
    add(admin, playlist, album_id=library["albums"]["Rock Album"]["id"])
    full = admin.post(f"/api/player/playlists/{playlist['id']}/tracks", json={"track_id": library["tracks"]["First"]["id"]}, headers=CSRF)
    assert full.status_code == 409
    create(admin, "Two")
    assert admin.post("/api/player/playlists", json={"name": "Three"}, headers=CSRF).status_code == 409


# --- who sees what --------------------------------------------------------------------


def test_playlists_are_private_but_panel_playlists_are_shared(admin, library):
    mine = create(admin, "Admin private")
    panel = create(admin, "For the panel", panel=True)
    add(admin, panel, track_id=library["tracks"]["First"]["id"])
    assert panel["panel"] is True and panel["editable"] is True

    make_user(admin, "ana")
    login(admin, "ana")
    own = create(admin, "Ana's")
    listed = admin.get("/api/player/playlists").json()
    assert [(p["name"], p["panel"], p["editable"]) for p in listed] == [("Ana's", False, True), ("For the panel", True, False)]
    assert admin.get(f"/api/player/playlists/{mine['id']}").status_code == 404
    assert admin.put(f"/api/player/playlists/{mine['id']}", json={"name": "x"}, headers=CSRF).status_code == 404
    assert admin.delete(f"/api/player/playlists/{mine['id']}", headers=CSRF).status_code == 404

    shared = admin.get(f"/api/player/playlists/{panel['id']}").json()
    assert titles(shared) == ["First"] and shared["playlist"]["editable"] is False
    # Everybody may play it, nobody but an administrator may change it.
    assert admin.post(f"/api/player/playlists/{panel['id']}/tracks", json={"track_id": 1}, headers=CSRF).status_code == 403
    assert admin.delete(f"/api/player/playlists/{panel['id']}", headers=CSRF).status_code == 403
    assert admin.post("/api/player/playlists", json={"name": "Mine too", "panel": True}, headers=CSRF).status_code == 403
    # And the other way round: the playlist of a user is not the administrator's to see.
    login(admin, "admin", "admin")
    assert admin.get(f"/api/player/playlists/{own['id']}").status_code == 404


def test_deleting_a_user_removes_the_playlists(admin, library):
    make_user(admin, "ana")
    login(admin, "ana")
    own = create(admin, "Ana's")
    add(admin, own, track_id=library["tracks"]["First"]["id"])
    login(admin, "admin", "admin")
    users = admin.get("/api/users").json()
    ana = next(u for u in users if u["username"] == "ana")
    assert admin.delete(f"/api/users/{ana['id']}", headers=CSRF).status_code == 204
    from homestart.db import SessionLocal
    from homestart.models import Playlist, PlaylistTrack

    with SessionLocal() as db:
        assert db.query(Playlist).filter(Playlist.name == "Ana's").count() == 0
        assert db.query(PlaylistTrack).count() == 0


# --- tracks that go away ------------------------------------------------------------------


def test_missing_tracks_stay_on_the_list_but_are_skipped(admin, library):
    playlist = create(admin)
    add(admin, playlist, album_id=library["albums"]["Rock Album"]["id"])
    (library["music"] / "Rock Album" / "02 - Second.mp3").unlink()
    scan(admin, library["source"]["id"])
    detail = admin.get(f"/api/player/playlists/{playlist['id']}").json()
    assert titles(detail) == ["First", "Second", "Štogod"]
    assert [t["available"] for t in detail["tracks"]] == [True, False, True]
    assert detail["playlist"]["tracks"] == 3 and detail["playlist"]["playable"] == 2

    played = admin.post("/api/player/session/command", json={"client_id": CLIENT, "action": "play", "playlist_id": playlist["id"]}, headers=CSRF).json()
    assert [t["title"] for t in played["queue"]] == ["First", "Štogod"]

    # Removed from the library for good, the entry goes too.
    admin.post(f"/api/config/player/sources/{library['source']['id']}/remove-missing", headers=CSRF)
    assert titles(admin.get(f"/api/player/playlists/{playlist['id']}").json()) == ["First", "Štogod"]


def test_a_switched_off_location_cannot_be_played_from_a_playlist(admin, library):
    playlist = create(admin)
    add(admin, playlist, track_id=library["tracks"]["First"]["id"])
    body = {"name": "Music", "path": library["source"]["path"], "enabled": False}
    admin.put(f"/api/config/player/sources/{library['source']['id']}", json=body, headers=CSRF)
    detail = admin.get(f"/api/player/playlists/{playlist['id']}").json()
    assert detail["tracks"][0]["available"] is False and detail["playlist"]["playable"] == 0
    nothing = admin.post("/api/player/session/command", json={"client_id": CLIENT, "action": "play", "playlist_id": playlist["id"]}, headers=CSRF)
    assert nothing.status_code == 404


# --- playing -----------------------------------------------------------------------------------


def test_playing_a_playlist(admin, library):
    playlist = create(admin)
    tracks = library["tracks"]
    add(admin, playlist, track_ids=[tracks["Štogod"]["id"], tracks["First"]["id"], tracks["Nameless"]["id"]])
    command = lambda **body: admin.post("/api/player/session/command", json={"client_id": CLIENT, **body}, headers=CSRF).json()  # noqa: E731
    state = command(action="play", playlist_id=playlist["id"], start_track_id=tracks["First"]["id"])
    assert [t["title"] for t in state["queue"]] == ["Štogod", "First", "Nameless"] and state["index"] == 1
    state = command(action="enqueue", playlist_id=playlist["id"])
    assert len(state["queue"]) == 6
    # Somebody else's playlist cannot be played.
    other = create(admin, "other")
    make_user(admin, "bob")
    login(admin, "bob")
    denied = admin.post("/api/player/session/command", json={"client_id": CLIENT, "action": "play", "playlist_id": other["id"]}, headers=CSRF)
    assert denied.status_code == 404


# --- the openpanel content ----------------------------------------------------------------------


def panel_add(client, **body):
    return client.post("/api/config/player/panel/items", json=body, headers=CSRF)


def test_panel_content(admin, library):
    tracks, albums = library["tracks"], library["albums"]
    panel = create(admin, "Evening", panel=True)
    add(admin, panel, track_id=tracks["First"]["id"])
    own = create(admin, "Private")

    favorite = panel_add(admin, section="favorites", kind="track", ref=str(tracks["First"]["id"]), title="  My song ")
    assert favorite.status_code == 201
    assert favorite.json()["title"] == "My song" and favorite.json()["name"] == "First – The Band" and favorite.json()["available"] is True
    assert panel_add(admin, section="favorites", kind="track", ref=str(tracks["Second"]["id"])).status_code == 201
    assert panel_add(admin, section="suggestions", kind="album", ref=str(albums["Rock Album"]["id"])).status_code == 201
    folder = panel_add(admin, section="suggestions", kind="folder", ref=f"{library['source']['id']}:/Untagged Band/")
    assert folder.status_code == 201 and folder.json()["ref"] == f"{library['source']['id']}:Untagged Band"
    assert folder.json()["name"] == "Music/Untagged Band"
    assert panel_add(admin, section="suggestions", kind="playlist", ref=str(panel["id"])).status_code == 201

    content = admin.get("/api/config/player/panel").json()
    assert [i["name"] for i in content["favorites"]] == ["First – The Band", "Second – The Band"]
    assert [i["kind"] for i in content["suggestions"]] == ["album", "folder", "playlist"]
    assert [p["name"] for p in content["playlists"]] == ["Evening"]  # panel playlists only

    # Mistakes.
    assert panel_add(admin, section="favorites", kind="album", ref="1").status_code == 400
    assert panel_add(admin, section="suggestions", kind="track", ref="1").status_code == 400
    assert panel_add(admin, section="suggestions", kind="playlist", ref=str(own["id"])).status_code == 404
    assert panel_add(admin, section="suggestions", kind="album", ref="99999").status_code == 404
    assert panel_add(admin, section="suggestions", kind="folder", ref="99999:x").status_code == 400
    assert panel_add(admin, section="suggestions", kind="album", ref="abc").status_code == 400
    assert panel_add(admin, section="suggestions", kind="album", ref=str(albums["Rock Album"]["id"])).status_code == 409
    assert panel_add(admin, section="bogus", kind="album", ref="1").status_code == 422


def test_panel_order_titles_and_removal(admin, library):
    tracks = library["tracks"]
    ids = [panel_add(admin, section="favorites", kind="track", ref=str(tracks[t]["id"])).json()["id"] for t in ("First", "Second", "Štogod")]
    reordered = admin.put("/api/config/player/panel/favorites/order", json={"ids": ids[::-1]}, headers=CSRF).json()
    assert [i["id"] for i in reordered["favorites"]] == ids[::-1]
    assert admin.put("/api/config/player/panel/favorites/order", json={"ids": ids[:2]}, headers=CSRF).status_code == 400
    assert admin.put("/api/config/player/panel/nonsense/order", json={"ids": []}, headers=CSRF).status_code == 404
    renamed = admin.put(f"/api/config/player/panel/items/{ids[0]}", json={"title": "Renamed"}, headers=CSRF).json()
    assert renamed["title"] == "Renamed"
    assert admin.put(f"/api/config/player/panel/items/{ids[0]}", json={"title": ""}, headers=CSRF).json()["title"] is None
    assert admin.delete(f"/api/config/player/panel/items/{ids[1]}", headers=CSRF).status_code == 204
    assert admin.delete(f"/api/config/player/panel/items/{ids[1]}", headers=CSRF).status_code == 404
    assert len(admin.get("/api/config/player/panel").json()["favorites"]) == 2


def test_panel_items_notice_what_goes_away(admin, library):
    tracks = library["tracks"]
    panel = create(admin, "Evening", panel=True)
    add(admin, panel, track_id=tracks["First"]["id"])
    panel_add(admin, section="favorites", kind="track", ref=str(tracks["Second"]["id"]))
    panel_add(admin, section="suggestions", kind="playlist", ref=str(panel["id"]))
    (library["music"] / "Rock Album" / "02 - Second.mp3").unlink()
    scan(admin, library["source"]["id"])
    content = admin.get("/api/player/panel").json()
    assert content["favorites"][0]["available"] is False and content["suggestions"][0]["available"] is True
    # A panel playlist that is deleted leaves the suggestions with it.
    assert admin.delete(f"/api/player/playlists/{panel['id']}", headers=CSRF).status_code == 204
    assert admin.get("/api/player/panel").json()["suggestions"] == []


def test_panel_management_is_for_administrators(admin, library):
    make_user(admin, "ana")
    login(admin, "ana")
    assert panel_add(admin, section="favorites", kind="track", ref="1").status_code == 403
    assert admin.get("/api/config/player/panel").status_code == 403
    assert admin.delete("/api/config/player/panel/items/1", headers=CSRF).status_code == 403
    # What the panel shows can be read by every logged-in user.
    assert admin.get("/api/player/panel").status_code == 200
    admin.post("/api/auth/logout", headers=CSRF)
    assert admin.get("/api/player/panel").status_code == 401


def test_migration_to_playlists(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    from homestart.db import make_engine
    from homestart.main import MIGRATIONS_DIR

    engine = make_engine(tmp_path / "old.db")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    for revision in ("0009", "head"):
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
    assert {"playlists", "playlist_tracks", "panel_items"} <= set(inspect(engine).get_table_names())

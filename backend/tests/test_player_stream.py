import asyncio
import os

import pytest
from test_player import CSRF, FRAME, add_source, admin, client, make_mp3, music, scan  # noqa: F401 - fixtures

from homestart.services.player.files import RangeNotSatisfiable, parse_range
from homestart.services.player.hub import HubFull, PlayerHub

CLIENT = "client-0001"


@pytest.fixture
def library(admin, music):  # noqa: F811
    source = add_source(admin, music)
    scan(admin, source["id"])
    tracks = admin.get("/api/player/tracks", params={"limit": 100}).json()["items"]
    return {"source": source, "tracks": {t["title"]: t for t in tracks}, "music": music}


def command(client, action, **fields):
    response = client.post("/api/player/session/command", json={"client_id": CLIENT, "action": action, **fields}, headers=CSRF)
    assert response.status_code == 200, response.text
    return response.json()


def titles(state):
    return [t["title"] for t in state["queue"]]


def current(state):
    return state["queue"][state["index"]]["title"] if state["queue"] else None


# --- Range ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "header, expected",
    [
        (None, None),
        ("bytes=0-99", (0, 99)),
        ("bytes=100-", (100, 999)),
        ("bytes=-50", (950, 999)),
        ("bytes=900-5000", (900, 999)),
        ("bytes=-5000", (0, 999)),
        ("bytes=0-1,5-9", None),
        ("items=0-1", None),
        ("bytes=abc", None),
    ],
)
def test_parse_range(header, expected):
    assert parse_range(header, 1000) == expected


@pytest.mark.parametrize("header", ["bytes=1000-", "bytes=2000-3000", "bytes=-0", "bytes=500-100"])
def test_parse_range_not_satisfiable(header):
    with pytest.raises(RangeNotSatisfiable):
        parse_range(header, 1000)


# --- streaming ---------------------------------------------------------------------


def stream_url(track, sid=CLIENT):
    return f"/player/stream/{track['id']}?sid={sid}"


def file_of(library, title):
    return next(library["music"].rglob(f"*{title}*.mp3"), None) or next(library["music"].rglob("*.mp3"))


def test_stream_requires_login(client):
    assert client.get("/player/stream/1").status_code == 401


def test_whole_file(admin, library):
    track = library["tracks"]["First"]
    expected = (library["music"] / "Rock Album" / "01 - First.mp3").read_bytes()
    response = admin.get(stream_url(track))
    assert response.status_code == 200
    assert response.content == expected
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["content-length"] == str(len(expected))
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-encoding"] == "identity"
    assert admin.app.state.player.listeners() == 0  # the stream was released


def test_ranges(admin, library):
    track = library["tracks"]["First"]
    data = (library["music"] / "Rock Album" / "01 - First.mp3").read_bytes()
    size = len(data)

    part = admin.get(stream_url(track), headers={"Range": "bytes=10-109"})
    assert part.status_code == 206 and part.content == data[10:110]
    assert part.headers["content-range"] == f"bytes 10-109/{size}" and part.headers["content-length"] == "100"

    tail = admin.get(stream_url(track), headers={"Range": "bytes=-40"})
    assert tail.status_code == 206 and tail.content == data[-40:]

    open_end = admin.get(stream_url(track), headers={"Range": f"bytes={size - 5}-"})
    assert open_end.status_code == 206 and open_end.content == data[-5:]

    beyond = admin.get(stream_url(track), headers={"Range": f"bytes={size}-"})
    assert beyond.status_code == 416 and beyond.headers["content-range"] == f"bytes */{size}"

    multi = admin.get(stream_url(track), headers={"Range": "bytes=0-1,5-9"})
    assert multi.status_code == 200 and multi.content == data


def test_head_does_not_send_the_file(admin, library):
    track = library["tracks"]["First"]
    response = admin.head(stream_url(track))
    assert response.status_code == 200 and response.content == b""
    assert int(response.headers["content-length"]) > 0
    assert admin.app.state.player.listeners() == 0


def test_unknown_and_missing_tracks(admin, library):
    assert admin.get("/player/stream/99999").status_code == 404
    track = library["tracks"]["Second"]
    (library["music"] / "Rock Album" / "02 - Second.mp3").unlink()
    # Gone from the disk but not yet rescanned: the source cannot answer.
    assert admin.get(stream_url(track)).status_code == 502
    assert admin.app.state.player.listeners() == 0
    scan(admin, library["source"]["id"])
    assert admin.get(stream_url(track)).status_code == 404


def test_disabled_location_cannot_be_streamed(admin, library):
    track = library["tracks"]["First"]
    body = {"name": "Music", "path": library["source"]["path"], "enabled": False}
    assert admin.put(f"/api/config/player/sources/{library['source']['id']}", json=body, headers=CSRF).status_code == 200
    assert admin.get(stream_url(track)).status_code == 404


def test_link_out_of_the_location_is_not_streamed(admin, library, tmp_path):
    track = library["tracks"]["First"]
    secret = tmp_path / "secret.mp3"
    secret.write_bytes(b"secret data")
    target = library["music"] / "Rock Album" / "01 - First.mp3"
    target.unlink()
    os.symlink(secret, target)
    response = admin.get(stream_url(track))
    assert response.status_code == 502 and b"secret" not in response.content


def test_listener_limit():
    hub = PlayerHub(max_listeners=2)
    release_a = hub.acquire_stream("a")
    hub.acquire_stream("b")
    with pytest.raises(HubFull):
        hub.acquire_stream("c")
    hub.acquire_stream("a")  # a second stream of a listener already counted is not a new listener
    assert hub.listeners() == 2
    release_a()
    release_a()  # releasing twice does no harm
    assert hub.listeners() == 2
    hub._streams.pop("a")
    hub.acquire_stream("c")
    assert hub.listeners() == 2


def test_full_hub_answers_503(admin, library):
    track = library["tracks"]["First"]
    hub = admin.app.state.player
    hub.max_listeners = 1
    hub.acquire_stream("someone-else")
    assert admin.get(stream_url(track)).status_code == 503


# --- the queue --------------------------------------------------------------------


def album_id(admin, title):
    return next(a["id"] for a in admin.get("/api/player/albums").json()["items"] if a["title"] == title)


def test_play_album_and_move_through_it(admin, library):
    state = command(admin, "play", album_id=album_id(admin, "Rock Album"))
    assert state["status"] == "playing" and titles(state) == ["First", "Second", "Štogod"] and current(state) == "First"
    assert state["next_id"] == state["queue"][1]["id"]

    assert current(command(admin, "next")) == "Second"
    assert current(command(admin, "prev")) == "First"
    assert current(command(admin, "prev")) == "First"  # nothing before the first track
    command(admin, "next"), command(admin, "next")
    end = command(admin, "next")
    assert end["status"] == "stopped" and end["index"] == 0

    assert command(admin, "resume")["status"] == "playing"
    assert command(admin, "pause")["status"] == "paused"
    stopped = command(admin, "stop")
    assert stopped["status"] == "stopped" and len(stopped["queue"]) == 3


def test_play_from_a_track_and_a_folder(admin, library):
    second = library["tracks"]["Second"]
    state = command(admin, "play", album_id=album_id(admin, "Rock Album"), start_track_id=second["id"])
    assert current(state) == "Second" and state["index"] == 1

    make_mp3(library["music"] / "Rock Album" / "Live" / "A.mp3", "Live one", "The Band", "Live", 1)
    scan(admin, library["source"]["id"])
    folder = command(admin, "play", source_id=library["source"]["id"], path="Rock Album")
    assert titles(folder) == ["First", "Second", "Štogod", "Live one"]  # the folder's own tracks, then its subfolders
    root = command(admin, "play", source_id=library["source"]["id"])
    assert len(root["queue"]) == 6


def test_single_track_and_a_list(admin, library):
    one = command(admin, "play", track_id=library["tracks"]["Štogod"]["id"])
    assert titles(one) == ["Štogod"]
    ids = [library["tracks"][t]["id"] for t in ("Second", "First", "Nameless")]
    several = command(admin, "play", track_ids=ids + [99999])
    assert titles(several) == ["Second", "First", "Nameless"]


def test_enqueue_and_play_next(admin, library):
    first, second, third = (library["tracks"][t]["id"] for t in ("First", "Second", "Štogod"))
    started = command(admin, "enqueue", track_id=first)  # an empty queue starts playing
    assert started["status"] == "playing" and titles(started) == ["First"]
    assert titles(command(admin, "enqueue", track_id=third)) == ["First", "Štogod"]
    assert titles(command(admin, "play_next", track_id=second)) == ["First", "Second", "Štogod"]


def test_shuffle_keeps_the_track_and_restores_the_order(admin, library):
    state = command(admin, "play", album_id=album_id(admin, "Rock Album"))
    command(admin, "next")
    shuffled = command(admin, "shuffle", on=True)
    assert shuffled["shuffle"] and current(shuffled) == "Second"
    assert sorted(titles(shuffled)) == ["First", "Second", "Štogod"]
    assert shuffled["queue"][: shuffled["index"] + 1][-1]["title"] == "Second"
    restored = command(admin, "shuffle", on=False)
    assert titles(restored) == ["First", "Second", "Štogod"] and current(restored) == "Second"
    # A new album played while shuffle is on starts shuffled.
    command(admin, "shuffle", on=True)
    again = command(admin, "play", album_id=album_id(admin, "Rock Album"))
    assert sorted(titles(again)) == ["First", "Second", "Štogod"]
    start = command(admin, "play", album_id=album_id(admin, "Rock Album"), start_track_id=state["queue"][2]["id"])
    assert current(start) == "Štogod" and start["index"] == 0


def test_repeat_modes(admin, library):
    command(admin, "play", album_id=album_id(admin, "Rock Album"))
    command(admin, "next"), command(admin, "next")
    assert command(admin, "repeat", mode="all")["next_id"] is not None  # the last track is followed by the first
    wrapped = command(admin, "ended")
    assert current(wrapped) == "First" and wrapped["status"] == "playing"
    assert command(admin, "repeat", mode="one")["next_id"] is None
    assert command(admin, "repeat", mode="off")["repeat"] == "off"


def test_errors_skip_and_then_stop(admin, library):
    command(admin, "play", album_id=album_id(admin, "Rock Album"))
    assert current(command(admin, "error")) == "Second"
    assert current(command(admin, "error")) == "Štogod"
    stopped = command(admin, "error")
    assert stopped["status"] == "stopped"


def test_jump_and_clear(admin, library):
    command(admin, "play", album_id=album_id(admin, "Rock Album"))
    jumped = command(admin, "jump", index=2)
    assert current(jumped) == "Štogod"
    bad = admin.post("/api/player/session/command", json={"client_id": CLIENT, "action": "jump", "index": 9}, headers=CSRF)
    assert bad.status_code == 400
    cleared = command(admin, "clear")
    assert cleared["queue"] == [] and cleared["status"] == "stopped"


def test_command_validation(admin, library):
    post = lambda body: admin.post("/api/player/session/command", json={"client_id": CLIENT, **body}, headers=CSRF)  # noqa: E731
    assert post({"action": "play"}).status_code == 400
    assert post({"action": "play", "album_id": 99999}).status_code == 404
    assert post({"action": "shuffle"}).status_code == 400
    assert post({"action": "repeat"}).status_code == 400
    assert post({"action": "fly"}).status_code == 422
    short = admin.post("/api/player/session/command", json={"client_id": "x", "action": "stop"}, headers=CSRF)
    assert short.status_code == 422
    assert admin.post("/api/player/session/command", json={"client_id": CLIENT, "action": "stop"}).status_code == 403  # no CSRF header


def test_sessions_are_separate(admin, library):
    command(admin, "play", album_id=album_id(admin, "Rock Album"))
    other = admin.post(
        "/api/player/session/command",
        json={"client_id": "client-0002", "action": "play", "track_id": library["tracks"]["Nameless"]["id"]},
        headers=CSRF,
    ).json()
    assert titles(other) == ["Nameless"]
    mine = admin.get("/api/player/session", params={"client_id": CLIENT}).json()
    assert len(mine["queue"]) == 3

    admin.post("/api/users", json={"username": "ana", "password": "password-123", "role": "user"}, headers=CSRF)
    admin.post("/api/auth/logout", headers=CSRF)
    admin.post("/api/auth/login", json={"username": "ana", "password": "password-123"}, headers=CSRF)
    # The same client id of another user is another session.
    assert admin.get("/api/player/session", params={"client_id": CLIENT}).json()["queue"] == []


def test_queue_loses_tracks_that_leave_the_library(admin, library):
    command(admin, "play", album_id=album_id(admin, "Rock Album"))
    command(admin, "next")
    (library["music"] / "Rock Album" / "01 - First.mp3").unlink()
    scan(admin, library["source"]["id"])
    state = admin.get("/api/player/session", params={"client_id": CLIENT}).json()
    assert titles(state) == ["Second", "Štogod"] and current(state) == "Second"
    for name in ("02 - Second.mp3", "03 - Third.mp3"):
        (library["music"] / "Rock Album" / name).unlink()
    scan(admin, library["source"]["id"])
    emptied = admin.get("/api/player/session", params={"client_id": CLIENT}).json()
    assert emptied["queue"] == [] and emptied["status"] == "stopped"


def test_a_change_wakes_the_listener():
    hub = PlayerHub(3)

    async def scenario():
        session = hub.session("u1:abc")
        assert await hub.wait_for_change(session, session.version, 0.05) is False
        waiting = asyncio.create_task(hub.wait_for_change(session, session.version, 5))
        await asyncio.sleep(0.05)
        await asyncio.get_running_loop().run_in_executor(None, hub.changed, session)  # from another thread
        assert await waiting is True
        assert await hub.wait_for_change(session, 0, 0.05) is True  # already newer than what the caller has

    asyncio.run(scenario())

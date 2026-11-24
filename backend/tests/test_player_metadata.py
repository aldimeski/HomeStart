"""Album pictures (files, folders, Cover Art Archive) and MusicBrainz, with a fake internet."""

import io
import json
import time

import httpx
import pytest
from mutagen.id3 import APIC, ID3
from PIL import Image
from test_player import CSRF, add_source, admin, client, make_mp3, music, scan  # noqa: F401 - fixtures

from homestart.db import SessionLocal
from homestart.models import MusicAlbum
from homestart.services.player.covers import SIZES, normalize
from homestart.services.player.metadata import MusicBrainz, lucene_quote

MBID = "0a3c4e8f-1b2d-4c5e-9f60-718293a4b5c6"


def picture(color=(200, 30, 30), size=(800, 600), fmt="PNG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, fmt)
    return out.getvalue()


def embed(path, data=None, mime="image/png"):
    tags = ID3(path)
    tags.add(APIC(encoding=0, mime=mime, type=3, desc="", data=data or picture()))
    tags.save(path, v2_version=3)


class FakeInternet:
    """Answers like MusicBrainz and the Cover Art Archive; remembers what was asked."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.releases = [
            {
                "id": MBID,
                "score": 100,
                "title": "Rock Album",
                "date": "2005-03-01",
                "artist-credit": [{"name": "The Band", "artist": {"name": "The Band"}}],
                "media": [{"track-count": 3}],
                "tags": [{"name": "garage rock", "count": 5}, {"name": "rock", "count": 2}],
            }
        ]
        self.search_status = 200
        self.cover = picture((20, 120, 200))
        self.cover_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "musicbrainz.org":
            if self.search_status != 200:
                return httpx.Response(self.search_status)
            return httpx.Response(200, json={"releases": self.releases})
        if request.url.host == "coverartarchive.org":
            # The real archive redirects to the file; the client has to follow.
            return httpx.Response(307, headers={"Location": "https://archive.org/download/mbid/front-500.png"})
        if request.url.host == "archive.org":
            return httpx.Response(self.cover_status, content=self.cover if self.cover_status == 200 else b"", headers={"Content-Type": "image/png"})
        return httpx.Response(404)

    def searches(self):
        return [r for r in self.requests if r.url.host == "musicbrainz.org"]


@pytest.fixture
def internet(admin):  # noqa: F811
    fake = FakeInternet()
    service = admin.app.state.player_metadata
    service.transport, service.interval = httpx.MockTransport(fake), 0
    return fake


def run_lookup(client):
    client.app.state.player_metadata.start()
    client.app.state.player_metadata.wait()


def go_online(client):
    assert client.put("/api/config/player/metadata", json={"online_enabled": True}, headers=CSRF).status_code == 200
    client.app.state.player_metadata.wait()


def album_by_title(client, title):
    return next(a for a in client.get("/api/player/albums", params={"limit": 100}).json()["items"] if a["title"] == title)


def cover_of(client, album, size=300):
    return client.get(f"/api/player/cover/{album['id']}", params={"size": size})


def library(admin, music):  # noqa: F811
    source = add_source(admin, music)
    scan(admin, source["id"])
    admin.app.state.player_metadata.wait()
    return source


# --- pictures from files and folders -------------------------------------------------------


def test_embedded_cover(admin, music):
    embed(music / "Rock Album" / "01 - First.mp3", picture((10, 200, 10)))
    library(admin, music)
    album = album_by_title(admin, "Rock Album")
    assert album["has_cover"] is True
    for size in SIZES:
        response = cover_of(admin, album, size)
        assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
        assert "no-cache" in response.headers["cache-control"] and "etag" in response.headers
        with Image.open(io.BytesIO(response.content)) as image:
            assert image.format == "JPEG" and max(image.size) <= size
    assert max(Image.open(io.BytesIO(cover_of(admin, album, 600).content)).size) == 600
    assert admin.get("/api/player/tracks", params={"q": "first"}).json()["items"][0]["has_cover"] is True


def test_cover_requires_login_and_a_known_size(admin, music):
    embed(music / "Rock Album" / "01 - First.mp3")
    library(admin, music)
    album = album_by_title(admin, "Rock Album")
    assert cover_of(admin, album, 123).status_code == 400
    assert admin.get("/api/player/cover/99999").status_code == 404
    admin.post("/api/auth/logout", headers=CSRF)
    assert cover_of(admin, album).status_code == 401


def test_album_without_a_picture(admin, music):
    library(admin, music)
    album = album_by_title(admin, "Rock Album")
    assert album["has_cover"] is False and cover_of(admin, album).status_code == 404


def test_folder_picture_and_the_order(admin, music):
    (music / "Untagged Band" / "Folder.JPG").write_bytes(picture((1, 2, 3), fmt="JPEG"))
    (music / "Untagged Band" / "cover.png").write_bytes(picture((9, 9, 9)))
    (music / "Rock Album" / "front.jpg").write_bytes(picture((50, 50, 50), fmt="JPEG"))
    embed(music / "Rock Album" / "02 - Second.mp3", picture((255, 255, 0)))
    library(admin, music)
    untagged = Image.open(io.BytesIO(cover_of(admin, album_by_title(admin, "Untagged Band")).content))
    # cover.png ranks before Folder.JPG.
    assert untagged.getpixel((5, 5)) == pytest.approx((9, 9, 9), abs=4)
    rock = Image.open(io.BytesIO(cover_of(admin, album_by_title(admin, "Rock Album")).content))
    assert rock.getpixel((5, 5))[0] > 200  # the embedded yellow one, not front.jpg


def test_unusable_pictures_are_ignored(admin, music):
    (music / "Rock Album" / "cover.jpg").write_text("this is not a picture")
    (music / "Untagged Band" / "cover.jpg").write_bytes(picture(size=(4, 4), fmt="JPEG"))
    embed(music / "Rock Album" / "01 - First.mp3", b"junk bytes")
    library(admin, music)
    assert album_by_title(admin, "Rock Album")["has_cover"] is False
    assert album_by_title(admin, "Untagged Band")["has_cover"] is False
    with pytest.raises(ValueError):
        normalize(b"GIF89a....")
    with pytest.raises(ValueError):
        normalize(picture(size=(10, 10)))


def test_a_picture_added_later_is_found_on_rescan(admin, music):
    source = library(admin, music)
    assert album_by_title(admin, "Rock Album")["has_cover"] is False
    (music / "Rock Album" / "cover.jpg").write_bytes(picture(fmt="JPEG"))
    make_mp3(music / "Rock Album" / "04 - Fourth.mp3", "Fourth", "The Band", "Rock Album", 4, "Rock")
    scan(admin, source["id"])
    admin.app.state.player_metadata.wait()
    assert album_by_title(admin, "Rock Album")["has_cover"] is True


def test_cleared_cache_is_rebuilt(admin, music):
    embed(music / "Rock Album" / "01 - First.mp3")
    library(admin, music)
    album = album_by_title(admin, "Rock Album")
    for file in (admin.app.state.settings.cache_dir / "covers").glob("*.jpg"):
        file.unlink()
    assert cover_of(admin, album).status_code == 404
    admin.app.state.player_metadata.wait()
    assert cover_of(admin, album).status_code == 200


# --- online data -----------------------------------------------------------------------------


def test_nothing_goes_out_while_online_lookup_is_off(admin, music, internet):
    library(admin, music)
    assert internet.requests == []
    status = admin.get("/api/config/player/metadata").json()
    assert status["online_enabled"] is False and status["pending"] == 0 and status["albums"] == 2


def test_lookup_fills_in_year_genre_and_cover(admin, music, internet):
    library(admin, music)
    go_online(admin)
    album = album_by_title(admin, "Rock Album")
    assert album["year"] == 2005 and album["has_cover"] is True
    with SessionLocal() as db:
        row = db.get(MusicAlbum, album["id"])
        assert (row.meta_status, row.mb_release_id, row.cover_source) == ("found", MBID, "online")
        assert row.genre == "Rock"  # the genre of the tracks stays; the online one only fills a gap

    query = internet.searches()[0].url.params["query"]
    assert query == 'release:"Rock Album" AND artist:"The Band"'
    assert all(r.url.host in ("musicbrainz.org", "coverartarchive.org", "archive.org") for r in internet.requests)
    assert not any(str(music) in str(r.url) or "Rock Album/" in str(r.url) for r in internet.requests)
    agent = internet.requests[0].headers["user-agent"]
    assert agent.startswith("HomeStart/")
    assert Image.open(io.BytesIO(cover_of(admin, album).content)).getpixel((5, 5))[2] > 150  # the blue one


def test_genre_gap_is_filled_online(admin, music, internet):
    for name in ("01 - First.mp3", "02 - Second.mp3", "03 - Third.mp3"):
        make_mp3(music / "Rock Album" / name, "T" + name[:2], "The Band", "Rock Album", int(name[:2]))
    library(admin, music)
    go_online(admin)
    assert album_by_title(admin, "Rock Album")["genre"] == "garage rock"


def test_local_picture_wins_over_the_online_one(admin, music, internet):
    embed(music / "Rock Album" / "01 - First.mp3", picture((255, 255, 0)))
    library(admin, music)
    go_online(admin)
    assert not [r for r in internet.requests if r.url.host != "musicbrainz.org"]  # no picture was asked for
    with SessionLocal() as db:
        assert db.get(MusicAlbum, album_by_title(admin, "Rock Album")["id"]).cover_source == "embedded"


def test_album_that_is_not_found_is_left_alone_for_a_while(admin, music, internet):
    internet.releases = [{"id": MBID, "score": 100, "title": "Another Album", "artist-credit": [{"name": "The Band"}]}]
    library(admin, music)
    go_online(admin)
    first = len(internet.searches())
    assert first == 2  # one question per album
    with SessionLocal() as db:
        assert {a.meta_status for a in db.query(MusicAlbum)} == {"not_found"}
    run_lookup(admin)
    assert len(internet.searches()) == first  # not asked again
    assert admin.post("/api/config/player/metadata/retry", headers=CSRF).status_code == 202
    admin.app.state.player_metadata.wait()
    assert len(internet.searches()) == first * 2


@pytest.mark.parametrize(
    "change",
    [{"score": 50}, {"title": "Different"}, {"artist-credit": [{"name": "Somebody Else"}]}],
    ids=["low score", "other title", "other artist"],
)
def test_poor_matches_are_not_used(admin, music, internet, change):
    internet.releases[0].update(change)
    library(admin, music)
    go_online(admin)
    assert album_by_title(admin, "Rock Album")["year"] is None


def test_best_release_is_chosen_by_track_count(admin, music, internet):
    other = {**internet.releases[0], "id": "11111111-2222-4333-8444-555555555555", "media": [{"track-count": 12}], "date": "1999"}
    internet.releases = [other, internet.releases[0]]
    library(admin, music)
    go_online(admin)
    with SessionLocal() as db:
        assert db.get(MusicAlbum, album_by_title(admin, "Rock Album")["id"]).mb_release_id == MBID


def test_service_trouble_is_retried_after_an_hour(admin, music, internet):
    internet.search_status = 503
    library(admin, music)
    go_online(admin)
    with SessionLocal() as db:
        assert {a.meta_status for a in db.query(MusicAlbum)} == {"error"}
    asked = len(internet.requests)
    run_lookup(admin)
    assert len(internet.requests) == asked  # too soon
    internet.search_status = 200
    from datetime import timedelta

    from homestart.models import utcnow

    with SessionLocal() as db:
        for album in db.query(MusicAlbum):
            album.meta_checked_at = utcnow() - timedelta(hours=2)
        db.commit()
    run_lookup(admin)
    assert album_by_title(admin, "Rock Album")["year"] == 2005


def test_no_internet_is_an_error_not_a_crash(admin, music):
    def offline(request):
        raise httpx.ConnectError("no route")

    service = admin.app.state.player_metadata
    service.transport, service.interval = httpx.MockTransport(offline), 0
    library(admin, music)
    go_online(admin)
    status = admin.get("/api/config/player/metadata").json()
    assert status["errors"] == 2 and status["running"] is False
    assert admin.get("/api/player/albums").json()["total"] == 2


def test_refresh_one_album(admin, music, internet):
    library(admin, music)
    go_online(admin)
    album = album_by_title(admin, "Rock Album")
    internet.releases[0]["date"] = "2011"
    assert admin.post(f"/api/config/player/albums/{album['id']}/refresh", headers=CSRF).status_code == 202
    admin.app.state.player_metadata.wait()
    # The year was already known, so it stays; the picture is fetched again.
    assert album_by_title(admin, "Rock Album")["has_cover"] is True
    assert admin.post("/api/config/player/albums/99999/refresh", headers=CSRF).status_code == 404


def test_metadata_is_for_administrators(admin):
    admin.post("/api/users", json={"username": "ana", "password": "password-123", "role": "user"}, headers=CSRF)
    admin.post("/api/auth/logout", headers=CSRF)
    admin.post("/api/auth/login", json={"username": "ana", "password": "password-123"}, headers=CSRF)
    assert admin.get("/api/config/player/metadata").status_code == 403
    assert admin.put("/api/config/player/metadata", json={"online_enabled": True}, headers=CSRF).status_code == 403
    assert admin.post("/api/config/player/metadata/run", headers=CSRF).status_code == 403


def test_the_switch_is_remembered(admin):
    assert admin.get("/api/config/player/metadata").json()["online_enabled"] is False
    go_online(admin)
    assert admin.get("/api/config/player/metadata").json()["online_enabled"] is True


# --- MusicBrainz details -----------------------------------------------------------------------------


def test_search_text_is_escaped():
    assert lucene_quote('Say "Hi" (live) + more') == 'Say \\"Hi\\" \\(live\\) \\+ more'


def test_requests_keep_their_distance():
    times = []

    def handler(request):
        times.append(time.monotonic())
        return httpx.Response(200, json={"releases": []})

    brainz = MusicBrainz(httpx.Client(transport=httpx.MockTransport(handler)), interval=0.2)
    for _ in range(3):
        brainz.find_release("Album", "Artist", 1)
    assert times[1] - times[0] >= 0.19 and times[2] - times[1] >= 0.19


# --- the migration ---------------------------------------------------------------------------------------------


def test_migration_keeps_the_albums_of_existing_tracks(tmp_path):
    """Upgrading a library scanned before this version must not detach any track from its album."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from homestart.db import make_engine
    from homestart.main import MIGRATIONS_DIR

    engine = make_engine(tmp_path / "old.db")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))

    def upgrade(revision):
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)

    upgrade("0008")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO music_sources (id, name, kind, enabled, created_at) VALUES (1, 'M', 'local', 1, '2026-01-01')"))
        connection.execute(text("INSERT INTO music_albums (id, album_key, title, artist) VALUES (7, 'k', 'Album', 'Artist')"))
        connection.execute(
            text(
                "INSERT INTO music_tracks (id, source_id, rel_path, folder, size, mtime, format, title, artist, album_id, tags_derived, available, search_text)"
                " VALUES (1, 1, 'a.mp3', '', 1, 1, 'mp3', 'T', 'Artist', 7, 0, 1, 't')"
            )
        )
    upgrade("head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT album_id FROM music_tracks WHERE id = 1")).scalar() == 7
        row = connection.execute(text("SELECT cover_checked, meta_status, cover_file FROM music_albums WHERE id = 7")).one()
        assert tuple(row) == (0, "pending", None)

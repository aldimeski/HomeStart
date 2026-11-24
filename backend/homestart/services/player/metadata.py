"""Album pictures and online data: MusicBrainz (year, genre) and the Cover Art Archive (front cover).

Only the artist and album names and the number of tracks are sent. Nothing is written back to the music files.
"""

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ...config import Settings
from ...db import SessionLocal
from ...models import AppSetting, MusicAlbum, MusicSource, MusicTrack, utcnow
from ..secret_box import SecretBox
from .covers import read_embedded, save_cover
from .files import MAX_IMAGE_BYTES, make_location
from .tags import UNKNOWN_ARTIST, VARIOUS_ARTISTS, fold

log = logging.getLogger("homestart.player")

APP_VERSION = "1.0"
ONLINE_KEY = "player.metadata_online"
MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2/release/"
COVER_ART_URL = "https://coverartarchive.org/release/{mbid}/front-500"
# MusicBrainz allows one request a second.
MIN_INTERVAL_SECONDS = 1.1
REQUEST_TIMEOUT_SECONDS = 15
ERROR_RETRY = timedelta(hours=1)
MIN_SCORE = 80
EMBEDDED_TRIES = 3
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


@dataclass
class Release:
    mbid: str
    year: int | None
    genre: str | None


def lucene_quote(text: str) -> str:
    return LUCENE_SPECIAL.sub(r"\\\1", text)


class MusicBrainz:
    def __init__(self, client: httpx.Client, interval: float):
        self._client = client
        self._interval = interval
        self._last = 0.0

    def _throttle(self) -> None:
        wait = self._last + self._interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def find_release(self, title: str, artist: str, tracks: int) -> Release | None:
        query = f'release:"{lucene_quote(title)}"'
        known_artist = artist not in (VARIOUS_ARTISTS, UNKNOWN_ARTIST)
        if known_artist:
            query += f' AND artist:"{lucene_quote(artist)}"'
        self._throttle()
        response = self._client.get(MUSICBRAINZ_URL, params={"query": query, "fmt": "json", "limit": 8})
        response.raise_for_status()
        best = None
        for release in response.json().get("releases", []):
            mbid = release.get("id", "")
            if not UUID.match(mbid) or release.get("score", 0) < MIN_SCORE or fold(release.get("title", "")) != fold(title):
                continue
            credits = " ".join(
                fold(c.get("name") or c.get("artist", {}).get("name", "")) for c in release.get("artist-credit", []) if isinstance(c, dict)
            )
            if known_artist and fold(artist) not in credits and credits not in fold(artist):
                continue
            count = sum(m.get("track-count", 0) for m in release.get("media", [])) or release.get("track-count", 0)
            rank = (count == tracks, release["score"], bool(release.get("date")))
            if best is None or rank > best[0]:
                best = (rank, release)
        if best is None:
            return None
        release = best[1]
        year = re.match(r"(\d{4})", release.get("date") or "")
        tags = sorted(release.get("tags", []), key=lambda t: -t.get("count", 0))
        return Release(release["id"], int(year.group(1)) if year else None, tags[0]["name"][:128] if tags else None)

    def front_cover(self, mbid: str) -> bytes | None:
        with self._client.stream("GET", COVER_ART_URL.format(mbid=mbid)) as response:
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = b""
            for chunk in response.iter_bytes():
                data += chunk
                if len(data) > MAX_IMAGE_BYTES:
                    return None
            return data


class MetadataService:
    """Looks for the picture and the online data of albums, one album after the other, in a background thread."""

    def __init__(self, settings: Settings, secret_box: SecretBox, transport: httpx.BaseTransport | None = None, interval: float = MIN_INTERVAL_SECONDS):
        self._settings = settings
        self._secret_box = secret_box
        self.transport = transport  # tests put a fake here
        self.interval = interval
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # --- the on/off switch ----------------------------------------------------------

    def online_enabled(self) -> bool:
        with SessionLocal() as db:
            row = db.get(AppSetting, ONLINE_KEY)
            if row is not None:
                return self._secret_box.decrypt(row.value_enc) == "1"
        return self._settings.player_metadata_online

    def set_online(self, enabled: bool) -> None:
        with SessionLocal() as db:
            db.merge(AppSetting(key=ONLINE_KEY, value_enc=self._secret_box.encrypt("1" if enabled else "0"), updated_at=utcnow()))
            db.commit()

    # --- what is left to do -----------------------------------------------------------

    def _due(self, online: bool):
        now = utcnow()
        recheck = timedelta(days=self._settings.player_metadata_recheck_days)
        conditions = [MusicAlbum.cover_checked.is_(False)]
        if online:
            conditions += [
                MusicAlbum.meta_status == "pending",
                and_(MusicAlbum.meta_status == "error", MusicAlbum.meta_checked_at < now - ERROR_RETRY),
                and_(MusicAlbum.meta_status == "not_found", MusicAlbum.meta_checked_at < now - recheck),
            ]
        live = select(MusicTrack.album_id).where(
            MusicTrack.available.is_(True), MusicTrack.source_id.in_(select(MusicSource.id).where(MusicSource.enabled.is_(True)))
        )
        return or_(*conditions), live

    def pending(self, db: Session) -> int:
        condition, live = self._due(self.online_enabled())
        return db.scalar(select(func.count()).select_from(MusicAlbum).where(MusicAlbum.id.in_(live), condition)) or 0

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> bool:
        """Starts working through the albums that need it; does nothing when that is already going on."""
        with self._lock:
            if self.running:
                return False
            self._thread = threading.Thread(target=self._run, name="player-metadata", daemon=True)
            self._thread.start()
            return True

    def wait(self, timeout: float = 30) -> None:
        thread = self._thread
        if thread:
            thread.join(timeout)

    # --- the work -----------------------------------------------------------------------

    def _run(self) -> None:
        online = self.online_enabled()
        headers = {
            "User-Agent": f"HomeStart/{APP_VERSION} ( {self._settings.player_musicbrainz_contact} )"
            if self._settings.player_musicbrainz_contact
            else f"HomeStart/{APP_VERSION}",
            "Accept": "application/json, image/*",
        }
        skip: set[int] = set()
        try:
            with httpx.Client(transport=self.transport, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
                brainz = MusicBrainz(client, self.interval)
                while True:
                    with SessionLocal() as db:
                        condition, live = self._due(online)
                        album = db.scalars(
                            select(MusicAlbum).where(MusicAlbum.id.in_(live), condition, MusicAlbum.id.not_in(skip)).order_by(MusicAlbum.id).limit(1)
                        ).first()
                        if album is None:
                            return
                        skip.add(album.id)
                        try:
                            self._process(db, album, brainz, online)
                        except Exception:  # noqa: BLE001 - one album must not stop the others
                            log.exception("Looking up album %s failed", album.id)
                            db.rollback()
                            continue
                        db.commit()
        except Exception:  # noqa: BLE001
            log.exception("Album lookup stopped")

    def _local_cover(self, db: Session, album: MusicAlbum) -> bool:
        """Looks for a picture in the files and the folder. False when the location could not be read (try again later)."""
        rows = db.execute(
            select(MusicTrack, MusicSource)
            .join(MusicSource, MusicSource.id == MusicTrack.source_id)
            .where(MusicTrack.album_id == album.id, MusicTrack.available.is_(True), MusicSource.enabled.is_(True))
            .order_by(MusicTrack.disc_no, MusicTrack.track_no, MusicTrack.title)
        ).all()
        if not rows:
            return True
        first, source = rows[0]
        location = make_location(self._settings, self._secret_box, source)
        candidates: list[tuple[str, bytes | None]] = []
        try:
            for track, _ in rows[:EMBEDDED_TRIES]:
                with location.open_for_tags(track.rel_path) as reader:
                    candidates.append(("embedded", read_embedded(reader, track.format)))
            candidates.append(("folder", location.read_folder_image(first.folder)))
        except OSError as exc:
            log.info("Cannot look for a cover of album %s: %s", album.id, exc)
            return False
        for origin, data in candidates:
            if not data:
                continue
            try:
                album.cover_file = save_cover(self._settings, album.id, data)
            except ValueError:
                continue
            album.cover_source = origin
            break
        album.cover_checked = True
        return True

    def _meta_due(self, album: MusicAlbum, online: bool) -> bool:
        if not online:
            return False
        now = utcnow()
        if album.meta_status == "pending":
            return True
        if album.meta_checked_at is None:
            return True
        wait = ERROR_RETRY if album.meta_status == "error" else timedelta(days=self._settings.player_metadata_recheck_days)
        return album.meta_status in ("error", "not_found") and album.meta_checked_at < now - wait

    def _process(self, db: Session, album: MusicAlbum, brainz: MusicBrainz, online: bool) -> None:
        if not album.cover_checked:
            self._local_cover(db, album)
        if not self._meta_due(album, online):
            return
        tracks = db.scalar(select(func.count()).select_from(MusicTrack).where(MusicTrack.album_id == album.id, MusicTrack.available.is_(True))) or 0
        try:
            release = brainz.find_release(album.title, album.artist, tracks)
            if release is None:
                album.meta_status = "not_found"
            else:
                album.meta_status = "found"
                album.mb_release_id = release.mbid
                album.year = album.year or release.year
                album.genre = album.genre or release.genre
                if not album.cover_file:
                    data = brainz.front_cover(release.mbid)
                    if data:
                        try:
                            album.cover_file = save_cover(self._settings, album.id, data)
                            album.cover_source = "online"
                        except ValueError:
                            pass
        except (httpx.HTTPError, ValueError, KeyError):
            # No internet, or the service is busy: tried again after a while.
            album.meta_status = "error"
        album.meta_checked_at = utcnow()

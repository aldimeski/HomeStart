"""Scans music locations and keeps the library (tracks and albums) in step with what is on them."""

import json
import logging
from collections.abc import Callable
import threading
from collections import Counter
from datetime import timedelta
from pathlib import PurePosixPath

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ...config import Settings
from ...db import SessionLocal
from ..secret_box import SecretBox
from .files import LocationError, WalkCancelled, make_location
from ...models import (
    SCAN_CANCELLED,
    SCAN_DONE,
    SCAN_FAILED,
    SCAN_RUNNING,
    MusicAlbum,
    MusicScan,
    MusicSource,
    MusicTrack,
    utcnow,
)
from .tags import UNKNOWN_ALBUM, VARIOUS_ARTISTS, TrackInfo, fold, read_track

log = logging.getLogger("homestart.player")

COMMIT_EVERY = 200
# A scan report lists at most this many files and folders per kind; the counts are always exact.
DETAIL_LIMIT = 5000


class ScanBusy(Exception):
    """Another scan is already running; only one location is read at a time."""


class ScanCancelled(Exception):
    pass


def folder_of(rel_path: str) -> str:
    return rel_path.rpartition("/")[0]


def folders_with_ancestors(folders: set[str]) -> set[str]:
    result = set()
    for folder in folders:
        while folder:
            result.add(folder)
            folder = folder.rpartition("/")[0]
    return result


def album_key(source_id: int, folder: str, info: TrackInfo) -> str:
    """Tracks of one album share the key: album and album artist, else the folder they are in."""
    if info.album_from_folder or not (info.album_artist or info.compilation):
        return f"f|{fold(info.album)}|{source_id}:{fold(folder)}"
    return f"a|{fold(info.album)}|{fold(info.album_artist or VARIOUS_ARTISTS)}"


def _apply(track: MusicTrack, info: TrackInfo, size: int, mtime: int) -> None:
    track.size = size
    track.mtime = mtime
    track.duration_s = info.duration_s
    track.bitrate = info.bitrate
    track.title = info.title
    track.artist = info.artist
    track.album_artist = info.album_artist
    track.track_no = info.track_no
    track.disc_no = info.disc_no
    track.year = info.year
    track.genre = info.genre
    track.tags_derived = info.derived
    track.available = True
    track.missing_since = None
    track.search_text = " ".join(fold(part) for part in (info.title, info.artist, info.album))


def refresh_album(db: Session, album_id: int) -> None:
    """Recalculates the album's artist, year and genre from its tracks, and removes an album without any."""
    tracks = db.scalars(select(MusicTrack).where(MusicTrack.album_id == album_id)).all()
    album = db.get(MusicAlbum, album_id)
    if album is None:
        return
    if not tracks:
        db.delete(album)
        return
    live = [t for t in tracks if t.available] or tracks
    album_artists = {t.album_artist for t in live if t.album_artist}
    artists = {t.artist for t in live}
    if album_artists:
        album.artist = Counter(t.album_artist for t in live if t.album_artist).most_common(1)[0][0]
    else:
        album.artist = next(iter(artists)) if len(artists) == 1 else VARIOUS_ARTISTS
    years = [t.year for t in live if t.year]
    # What the tags do not say stays as it was, as it may have come from the online lookup.
    album.year = min(years) if years else album.year
    genres = Counter(t.genre for t in live if t.genre)
    album.genre = genres.most_common(1)[0][0] if genres else album.genre


def purge_tracks(db: Session, track_ids: list[int]) -> None:
    """Removes tracks from the library and tidies the albums they leave behind."""
    if not track_ids:
        return
    album_ids = {a for a in db.scalars(select(MusicTrack.album_id).where(MusicTrack.id.in_(track_ids))) if a}
    db.execute(delete(MusicTrack).where(MusicTrack.id.in_(track_ids)))
    db.flush()
    for album_id in album_ids:
        refresh_album(db, album_id)


def _limited(items) -> list[str]:
    return sorted(items)[:DETAIL_LIMIT]


def scan_location(settings: Settings, secret_box: SecretBox, scan_id: int, cancel: threading.Event) -> None:
    """Runs one scan; every outcome is written to its music_scans row."""
    with SessionLocal() as db:
        scan = db.get(MusicScan, scan_id)
        source = db.get(MusicSource, scan.source_id)
        errors: list[str] = []
        details: dict = {}
        try:
            _scan(db, settings, secret_box, scan, source, cancel, errors, details)
            scan.status = SCAN_DONE
        except (ScanCancelled, WalkCancelled):
            db.rollback()
            scan = db.get(MusicScan, scan_id)
            scan.status = SCAN_CANCELLED
        except Exception as exc:  # noqa: BLE001 - the reason goes to the report, the log has the traceback
            log.exception("Scan of '%s' failed", source.name if source else scan.source_id)
            db.rollback()
            scan = db.get(MusicScan, scan_id)
            scan.status = SCAN_FAILED
            scan.error_message = str(exc) if isinstance(exc, LocationError | ValueError) else "Unexpected error, see the log"
        scan.finished_at = utcnow()
        scan.errors = len(errors)
        details["errors"] = errors[:100]
        scan.details_json = json.dumps(details)
        source = db.get(MusicSource, scan.source_id)
        if source is not None:
            source.last_scan_at = scan.finished_at
            source.last_scan_status = scan.status
        db.commit()
        log.info(
            "Scan of '%s' %s: %d added, %d changed, %d removed, %d errors",
            source.name if source else scan.source_id,
            scan.status,
            scan.added,
            scan.changed,
            scan.removed,
            scan.errors,
        )


def _scan(db: Session, settings: Settings, secret_box: SecretBox, scan: MusicScan, source: MusicSource, cancel, errors: list[str], details: dict) -> None:
    location = make_location(settings, secret_box, source)
    # A location that cannot be reached is not the same as deleted files: nothing is marked as removed.
    location.check()

    def on_error(exc: OSError) -> None:
        errors.append(f"{getattr(exc, 'filename', None) or ''}{': ' if getattr(exc, 'filename', None) else ''}{getattr(exc, 'strerror', None) or exc}")

    found = location.walk(settings.player_formats, cancel, on_error)
    existing = {t.rel_path: t for t in db.scalars(select(MusicTrack).where(MusicTrack.source_id == source.id))}

    before_folders = folders_with_ancestors({t.folder for t in existing.values() if t.available})
    after_folders = folders_with_ancestors({folder_of(rel) for rel in found})

    added: list[str] = []
    changed: list[str] = []
    touched_albums: set[int] = set()
    albums = {a.album_key: a for a in db.scalars(select(MusicAlbum))}

    for done, (rel, (size, mtime, fmt)) in enumerate(sorted(found.items()), start=1):
        if cancel.is_set():
            raise ScanCancelled
        track = existing.get(rel)
        if track and track.available and track.size == size and track.mtime == mtime:
            continue
        try:
            with location.open_for_tags(rel) as reader:
                info = read_track(reader, rel, fmt, settings.player_legacy_encoding)
        except OSError as exc:
            on_error(exc)
            continue
        folder = folder_of(rel)
        if track is None:
            track = MusicTrack(source_id=source.id, rel_path=rel, folder=folder, format=fmt)
            db.add(track)
            added.append(rel)
        elif track.available:
            changed.append(rel)
        else:
            added.append(rel)  # back after having disappeared
        if track.album_id:
            touched_albums.add(track.album_id)
        _apply(track, info, size, mtime)
        key = album_key(source.id, folder, info)
        album = albums.get(key)
        if album is None:
            album = MusicAlbum(album_key=key, title=info.album if info.album else UNKNOWN_ALBUM, artist=info.artist)
            db.add(album)
            db.flush()
            albums[key] = album
        track.album_id = album.id
        touched_albums.add(album.id)
        if done % COMMIT_EVERY == 0:
            db.flush()

    now = utcnow()
    removed = [rel for rel, t in existing.items() if t.available and rel not in found]
    for rel in removed:
        existing[rel].available = False
        existing[rel].missing_since = now
        if existing[rel].album_id:
            touched_albums.add(existing[rel].album_id)
    db.flush()

    expired = [
        t.id
        for t in existing.values()
        if not t.available and t.missing_since and t.missing_since < now - timedelta(days=settings.player_missing_keep_days)
    ]
    purge_tracks(db, expired)
    for album_id in touched_albums:
        refresh_album(db, album_id)
        album = db.get(MusicAlbum, album_id)
        if album is not None and not album.cover_file:
            album.cover_checked = False  # a picture may have been added with the new files

    scan.added, scan.changed, scan.removed = len(added), len(changed), len(removed)
    details.update(
        added=_limited(added),
        changed=_limited(changed),
        removed=_limited(removed),
        new_folders=_limited(after_folders - before_folders),
        removed_folders=_limited(before_folders - after_folders),
    )
    db.commit()


def remove_missing(db: Session, source_id: int) -> int:
    """Removes the files that disappeared from a location for good; returns how many."""
    ids = list(
        db.scalars(select(MusicTrack.id).where(MusicTrack.source_id == source_id, MusicTrack.available.is_(False)))
    )
    purge_tracks(db, ids)
    db.commit()
    return len(ids)


def delete_source_tracks(db: Session, source_id: int) -> None:
    ids = list(db.scalars(select(MusicTrack.id).where(MusicTrack.source_id == source_id)))
    purge_tracks(db, ids)


class ScanService:
    """Starts scans in the background, one at a time, and lets the administrator cancel them."""

    def __init__(self, settings: Settings, secret_box: SecretBox, on_done: Callable[[], None] | None = None):
        self._on_done = on_done
        self._settings = settings
        self._secret_box = secret_box
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._scan_id: int | None = None

    @property
    def active_scan_id(self) -> int | None:
        with self._lock:
            return self._scan_id if self._thread and self._thread.is_alive() else None

    def _busy(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, source_ids: list[int], user_id: int | None) -> int:
        """Starts scanning the locations one after the other; returns the number of the first scan."""
        with self._lock:
            if self._busy():
                raise ScanBusy
            with SessionLocal() as db:
                first = self._new_scan(db, source_ids[0], user_id)
            self._cancel = threading.Event()
            self._scan_id = first
            self._thread = threading.Thread(
                target=self._run, args=(first, source_ids[1:], user_id, self._cancel), name="player-scan", daemon=True
            )
            self._thread.start()
            return first

    @staticmethod
    def _new_scan(db: Session, source_id: int, user_id: int | None) -> int:
        scan = MusicScan(source_id=source_id, started_by=user_id, status=SCAN_RUNNING)
        db.add(scan)
        db.commit()
        return scan.id

    def _run(self, scan_id: int, more: list[int], user_id: int | None, cancel: threading.Event) -> None:
        try:
            scan_location(self._settings, self._secret_box, scan_id, cancel)
            for source_id in more:
                if cancel.is_set():
                    break
                with SessionLocal() as db:
                    if db.get(MusicSource, source_id) is None:
                        continue
                    next_id = self._new_scan(db, source_id, user_id)
                with self._lock:
                    self._scan_id = next_id
                scan_location(self._settings, self._secret_box, next_id, cancel)
        except Exception:  # noqa: BLE001
            log.exception("Scan thread stopped")
        finally:
            if self._on_done:
                self._on_done()

    def cancel(self) -> bool:
        with self._lock:
            if not self._busy():
                return False
            self._cancel.set()
            return True

    def wait(self, timeout: float = 30) -> None:
        thread = self._thread
        if thread:
            thread.join(timeout)


def mark_interrupted_scans() -> None:
    """After a restart no scan is running any more, whatever the database says."""
    with SessionLocal() as db:
        rows = db.scalars(select(MusicScan).where(MusicScan.status == SCAN_RUNNING)).all()
        for scan in rows:
            scan.status = SCAN_FAILED
            scan.error_message = "Interrupted by a restart"
            scan.finished_at = utcnow()
        db.commit()


def library_counts(db: Session, source_id: int) -> tuple[int, int]:
    available = db.scalar(
        select(func.count()).select_from(MusicTrack).where(MusicTrack.source_id == source_id, MusicTrack.available.is_(True))
    )
    missing = db.scalar(
        select(func.count()).select_from(MusicTrack).where(MusicTrack.source_id == source_id, MusicTrack.available.is_(False))
    )
    return available or 0, missing or 0

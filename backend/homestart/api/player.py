"""Player: the music library for every user, and the locations and scans for administrators."""

import json
import os
import threading
from contextvars import ContextVar
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import SOURCE_LOCAL, SOURCE_SMB, MusicAlbum, MusicScan, MusicSource, MusicTrack, User
from ..schemas import (
    AlbumDetail,
    AlbumOut,
    AlbumPage,
    FolderEntry,
    FolderListing,
    GenreOut,
    LocationOut,
    MusicScanDetail,
    MusicScanOut,
    MusicScanStarted,
    MetadataStatus,
    MetadataUpdate,
    MusicScanStatus,
    MusicSourceInput,
    MusicSourceOut,
    MusicSourceTestInput,
    MusicSourceTestResult,
    TrackOut,
    TrackPage,
)
from ..security import get_current_user, require_admin
from ..services.player.covers import SIZES, delete_covers, sized_cover
from ..services.player.files import LocationError, check_private_host, make_location, parse_network_path, reset_connections
from ..services.player.scanner import ScanBusy, ScanService, delete_source_tracks, library_counts, remove_missing
from ..services.player.tags import fold

router = APIRouter(prefix="/api/player", tags=["player"], dependencies=[Depends(get_current_user)])
admin_router = APIRouter(prefix="/api/config/player", tags=["player"])

PAGE_MAX = 200
# A connection test counts music files up to this many, so it stays quick on a big share.
TEST_FILE_LIMIT = 2000
FOLDER_TRACKS_MAX = 1000


def _scans(request: Request) -> ScanService:
    return request.app.state.player_scans


# --- the library ------------------------------------------------------------


# The file types the current request may see; None = all of them. The openpanel narrows it to what old tablets can play.
visible_formats: ContextVar[tuple[str, ...] | None] = ContextVar("visible_formats", default=None)


def _live() -> list:
    """What a listener may see: files that exist now, on locations that are switched on."""
    conditions = [MusicTrack.available.is_(True), MusicTrack.source_id.in_(select(MusicSource.id).where(MusicSource.enabled.is_(True)))]
    formats = visible_formats.get()
    if formats is not None:
        conditions.append(MusicTrack.format.in_(formats))
    return conditions


def _track_out(track: MusicTrack, album_title: str | None, cover_file: str | None) -> TrackOut:
    return TrackOut(
        id=track.id,
        title=track.title,
        artist=track.artist,
        album_id=track.album_id,
        album=album_title,
        track_no=track.track_no,
        disc_no=track.disc_no,
        year=track.year,
        genre=track.genre,
        duration_s=track.duration_s,
        format=track.format,
        has_cover=cover_file is not None,
    )


def _track_query() -> Select:
    return select(MusicTrack, MusicAlbum.title, MusicAlbum.cover_file).outerjoin(MusicAlbum, MusicAlbum.id == MusicTrack.album_id).where(*_live())


def _album_order():
    return MusicTrack.disc_no.is_(None), MusicTrack.disc_no, MusicTrack.track_no.is_(None), MusicTrack.track_no, MusicTrack.title


def _search_terms(q: str | None) -> list[str]:
    return fold(q).split() if q else []


def _filter_tracks(query: Select, q: str | None, genre: str | None, no_genre: bool) -> Select:
    for term in _search_terms(q):
        query = query.where(MusicTrack.search_text.contains(term, autoescape=True))
    if genre:
        query = query.where(func.lower(MusicTrack.genre) == genre.lower())
    if no_genre:
        query = query.where(MusicTrack.genre.is_(None))
    return query


@router.get("/tracks", response_model=TrackPage)
def list_tracks(
    q: str | None = Query(default=None, max_length=100),
    genre: str | None = Query(default=None, max_length=128),
    no_genre: bool = False,
    limit: int = Query(default=50, ge=1, le=PAGE_MAX),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = _filter_tracks(_track_query(), q, genre, no_genre)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = db.execute(query.order_by(MusicTrack.artist, MusicAlbum.title, *_album_order()).limit(limit).offset(offset)).all()
    return TrackPage(items=[_track_out(track, album, cover) for track, album, cover in rows], total=total or 0)


def _album_stats(q: str | None, genre: str | None, no_genre: bool):
    tracks = _filter_tracks(
        select(MusicTrack.album_id.label("album_id"), func.count().label("tracks"), func.coalesce(func.sum(MusicTrack.duration_s), 0.0).label("duration"))
        .where(*_live(), MusicTrack.album_id.is_not(None)),
        q,
        genre,
        no_genre,
    )
    return tracks.group_by(MusicTrack.album_id).subquery()


def _album_out(album: MusicAlbum, tracks: int, duration: float) -> AlbumOut:
    return AlbumOut(
        id=album.id,
        title=album.title,
        artist=album.artist,
        year=album.year,
        genre=album.genre,
        tracks=tracks,
        duration_s=duration,
        has_cover=album.cover_file is not None,
    )


@router.get("/albums", response_model=AlbumPage)
def list_albums(
    q: str | None = Query(default=None, max_length=100),
    genre: str | None = Query(default=None, max_length=128),
    no_genre: bool = False,
    sort: str = Query(default="title", pattern="^(title|artist|year)$"),
    limit: int = Query(default=50, ge=1, le=PAGE_MAX),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stats = _album_stats(q, genre, no_genre)
    query = select(MusicAlbum, stats.c.tracks, stats.c.duration).join(stats, stats.c.album_id == MusicAlbum.id)
    total = db.scalar(select(func.count()).select_from(stats))
    order = {
        "title": (func.lower(MusicAlbum.title), func.lower(MusicAlbum.artist)),
        "artist": (func.lower(MusicAlbum.artist), func.lower(MusicAlbum.title)),
        "year": (MusicAlbum.year.is_(None), MusicAlbum.year, func.lower(MusicAlbum.title)),
    }[sort]
    rows = db.execute(query.order_by(*order).limit(limit).offset(offset)).all()
    return AlbumPage(items=[_album_out(album, n, duration) for album, n, duration in rows], total=total or 0)


@router.get("/albums/{album_id}", response_model=AlbumDetail)
def get_album(album_id: int, db: Session = Depends(get_db)):
    album = db.get(MusicAlbum, album_id)
    rows = db.execute(_track_query().where(MusicTrack.album_id == album_id).order_by(*_album_order())).all()
    if album is None or not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Album not found")
    duration = sum(row[0].duration_s or 0 for row in rows)
    return AlbumDetail(album=_album_out(album, len(rows), duration), tracks=[_track_out(*row) for row in rows])


@router.get("/genres", response_model=list[GenreOut])
def list_genres(db: Session = Depends(get_db)):
    lowered = func.lower(MusicTrack.genre)
    rows = db.execute(
        select(func.min(MusicTrack.genre), func.count(), func.count(func.distinct(MusicTrack.album_id)))
        .where(*_live())
        .group_by(lowered)
        .order_by(lowered.is_(None), lowered)
    ).all()
    return [GenreOut(name=name, tracks=tracks, albums=albums) for name, tracks, albums in rows]


@router.get("/locations", response_model=list[LocationOut])
def list_locations(db: Session = Depends(get_db)):
    rows = db.execute(
        select(MusicSource.id, MusicSource.name, func.count(MusicTrack.id))
        .join(MusicTrack, (MusicTrack.source_id == MusicSource.id) & MusicTrack.available.is_(True), isouter=True)
        .where(MusicSource.enabled.is_(True))
        .group_by(MusicSource.id)
        .order_by(func.lower(MusicSource.name))
    ).all()
    return [LocationOut(id=i, name=name, tracks=tracks) for i, name, tracks in rows]


@router.get("/folders", response_model=FolderListing)
def list_folder(source_id: int, path: str = Query(default="", max_length=1000), db: Session = Depends(get_db)):
    source = db.get(MusicSource, source_id)
    if source is None or not source.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Location not found")
    path = path.strip("/")
    prefix = f"{path}/" if path else ""
    counts = db.execute(
        select(MusicTrack.folder, func.count()).where(*_live(), MusicTrack.source_id == source_id).group_by(MusicTrack.folder)
    ).all()
    children: dict[str, int] = {}
    here = 0
    for folder, count in counts:
        if folder == path:
            here += count
        elif folder.startswith(prefix):
            name = folder[len(prefix):].split("/", 1)[0]
            children[name] = children.get(name, 0) + count
    if path and not here and not children:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
    rows = db.execute(
        _track_query().where(MusicTrack.source_id == source_id, MusicTrack.folder == path).order_by(*_album_order()).limit(FOLDER_TRACKS_MAX)
    ).all()
    return FolderListing(
        source_id=source.id,
        source_name=source.name,
        path=path,
        folders=[FolderEntry(name=n, path=f"{prefix}{n}", tracks=c) for n, c in sorted(children.items(), key=lambda kv: kv[0].lower())],
        tracks=[_track_out(*row) for row in rows],
    )


# --- locations and scans (administrators) --------------------------------------


def _get_source(db: Session, source_id: int) -> MusicSource:
    source = db.get(MusicSource, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Location not found")
    return source


def _check_folder(path: str) -> str:
    folder = Path(path).expanduser()
    if not folder.is_absolute():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter the full path of the folder, starting with /")
    folder = folder.resolve()
    if not folder.is_dir():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This folder does not exist on the server")
    if not os.access(folder, os.R_OK | os.X_OK):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "HomeStart is not allowed to read this folder")
    return str(folder)


def _network_path(source: MusicSource) -> str | None:
    if source.kind != SOURCE_SMB:
        return None
    return "\\".join(["", "", source.host or "", source.share or "", *[p for p in (source.subpath or "").split("/") if p]])


def _source_out(db: Session, source: MusicSource, request: Request) -> MusicSourceOut:
    tracks, missing = library_counts(db, source.id)
    username = request.app.state.secret_box.decrypt(source.username_enc) if source.username_enc else None
    return MusicSourceOut(
        id=source.id,
        name=source.name,
        kind=source.kind,
        path=source.path,
        network_path=_network_path(source),
        username=username,
        has_password=bool(source.password_enc),
        enabled=source.enabled,
        last_scan_at=source.last_scan_at,
        last_scan_status=source.last_scan_status,
        tracks=tracks,
        missing=missing,
    )


def _fill(request: Request, source: MusicSource, body: MusicSourceInput) -> None:
    """Copies the input to the location; the password is encrypted, and left as it was when none is given."""
    box = request.app.state.secret_box
    source.name, source.enabled = body.name, body.enabled
    if body.kind == SOURCE_LOCAL:
        source.path = _check_folder(body.path)
        return
    host, share, subpath = parse_network_path(body.network_path)
    try:
        check_private_host(host)
    except LocationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    source.host, source.share, source.subpath = host, share, subpath or None
    source.username_enc = box.encrypt(body.username) if body.username else None
    if not body.username:
        source.password_enc = None  # a guest has no password
    elif body.password:
        source.password_enc = box.encrypt(body.password)
    reset_connections()


def _commit_unique(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Another location already has this name") from None


@admin_router.get("/sources", response_model=list[MusicSourceOut])
def list_sources(request: Request, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [_source_out(db, s, request) for s in db.scalars(select(MusicSource).order_by(func.lower(MusicSource.name)))]


@admin_router.post("/sources", response_model=MusicSourceOut, status_code=status.HTTP_201_CREATED)
def create_source(body: MusicSourceInput, request: Request, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    source = MusicSource(kind=body.kind)
    _fill(request, source, body)
    db.add(source)
    _commit_unique(db)
    return _source_out(db, source, request)


@admin_router.post("/sources/test", response_model=MusicSourceTestResult)
def test_source(body: MusicSourceTestInput, request: Request, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Tries the location without saving it: connects, reads it and counts the music files."""
    probe = MusicSource(kind=body.kind)
    saved = db.get(MusicSource, body.source_id) if body.source_id else None
    try:
        if body.kind == SOURCE_LOCAL:
            probe.path = body.path
        else:
            host, share, subpath = parse_network_path(body.network_path)
            box = request.app.state.secret_box
            probe.host, probe.share, probe.subpath = host, share, subpath or None
            probe.username_enc = box.encrypt(body.username) if body.username else None
            if body.username:
                if body.password:
                    probe.password_enc = box.encrypt(body.password)
                elif saved is not None and saved.kind == SOURCE_SMB:
                    probe.password_enc = saved.password_enc
        location = make_location(request.app.state.settings, request.app.state.secret_box, probe)
        location.check()
        found = location.walk(request.app.state.settings.player_formats, threading.Event(), lambda _exc: None, TEST_FILE_LIMIT)
    except (LocationError, ValueError) as exc:
        return MusicSourceTestResult(ok=False, message=str(exc))
    count = len(found)
    more = "+" if count >= TEST_FILE_LIMIT else ""
    return MusicSourceTestResult(ok=True, message=f"Connected. {count}{more} music files found.", tracks=count)


@admin_router.put("/sources/{source_id}", response_model=MusicSourceOut)
def update_source(source_id: int, body: MusicSourceInput, request: Request, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    source = _get_source(db, source_id)
    if body.kind != source.kind:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The kind of a location cannot be changed; add a new one")
    if _scanning_source(request, db, source_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "This location is being scanned; try again when the scan is over")
    _fill(request, source, body)
    _commit_unique(db)
    return _source_out(db, source, request)


def _scanning_source(request: Request, db: Session, source_id: int) -> bool:
    active = _scans(request).active_scan_id
    return bool(active and (scan := db.get(MusicScan, active)) and scan.source_id == source_id)


@admin_router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: int, request: Request, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    source = _get_source(db, source_id)
    if _scanning_source(request, db, source_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "This location is being scanned; cancel the scan first")
    # The files on the location are never touched; only the library entries go.
    delete_source_tracks(db, source_id)
    db.delete(source)
    db.commit()
    reset_connections()


def _start(request: Request, ids: list[int], user: User) -> MusicScanStarted:
    try:
        scan_id = _scans(request).start(ids, user.id)
    except ScanBusy:
        raise HTTPException(status.HTTP_409_CONFLICT, "A scan is already running") from None
    return MusicScanStarted(scan_id=scan_id, sources=len(ids))


@admin_router.post("/sources/{source_id}/scan", response_model=MusicScanStarted, status_code=status.HTTP_202_ACCEPTED)
def scan_source(source_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    source = _get_source(db, source_id)
    if not source.enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Switch the location on to scan it")
    return _start(request, [source.id], user)


@admin_router.post("/scan", response_model=MusicScanStarted, status_code=status.HTTP_202_ACCEPTED)
def scan_all(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    ids = list(db.scalars(select(MusicSource.id).where(MusicSource.enabled.is_(True)).order_by(MusicSource.id)))
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "There is no location switched on")
    return _start(request, ids, user)


@admin_router.post("/scan/cancel", status_code=status.HTTP_204_NO_CONTENT)
def cancel_scan(request: Request, _: User = Depends(require_admin)):
    if not _scans(request).cancel():
        raise HTTPException(status.HTTP_409_CONFLICT, "No scan is running")


@admin_router.get("/status", response_model=MusicScanStatus)
def scan_status(request: Request, _: User = Depends(require_admin)):
    active = _scans(request).active_scan_id
    return MusicScanStatus(scanning=active is not None, scan_id=active)


@admin_router.post("/sources/{source_id}/remove-missing")
def remove_missing_files(source_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    _get_source(db, source_id)
    return {"removed": remove_missing(db, source_id)}


def _scan_out(scan: MusicScan, user_name: str | None) -> dict:
    return dict(
        id=scan.id,
        source_id=scan.source_id,
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        started_by=user_name,
        status=scan.status,
        added=scan.added,
        changed=scan.changed,
        removed=scan.removed,
        errors=scan.errors,
        error_message=scan.error_message,
    )


@admin_router.get("/sources/{source_id}/scans", response_model=list[MusicScanOut])
def list_scans(source_id: int, limit: int = Query(default=10, ge=1, le=50), _: User = Depends(require_admin), db: Session = Depends(get_db)):
    _get_source(db, source_id)
    rows = db.execute(
        select(MusicScan, User.username)
        .join(User, User.id == MusicScan.started_by, isouter=True)
        .where(MusicScan.source_id == source_id)
        .order_by(MusicScan.id.desc())
        .limit(limit)
    ).all()
    return [MusicScanOut(**_scan_out(scan, name)) for scan, name in rows]


@admin_router.get("/scans/{scan_id}", response_model=MusicScanDetail)
def get_scan(scan_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.execute(
        select(MusicScan, User.username).join(User, User.id == MusicScan.started_by, isouter=True).where(MusicScan.id == scan_id)
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    scan, name = row
    details = json.loads(scan.details_json) if scan.details_json else {}
    return MusicScanDetail(
        **_scan_out(scan, name),
        added_files=details.get("added", []),
        changed_files=details.get("changed", []),
        removed_files=details.get("removed", []),
        new_folders=details.get("new_folders", []),
        removed_folders=details.get("removed_folders", []),
        error_list=details.get("errors", []),
    )


# --- pictures and online data ---------------------------------------------------------


@router.get("/cover/{album_id}")
def get_cover(album_id: int, request: Request, size: int = Query(default=300), db: Session = Depends(get_db)):
    if size not in SIZES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"The size must be one of {', '.join(map(str, SIZES))}")
    album = db.get(MusicAlbum, album_id)
    if album is None or not album.cover_file:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No picture")
    try:
        path = sized_cover(request.app.state.settings, album.cover_file, size)
        if not path.is_file():
            raise FileNotFoundError(path)
    except OSError:
        # The cache folder was cleared: the picture is looked for again.
        album.cover_file, album.cover_source, album.cover_checked = None, None, False
        db.commit()
        request.app.state.player_metadata.start()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No picture") from None
    # The address stays the same when the picture changes, so the browser asks again (the answer is a short 304).
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, no-cache"})


def _metadata_status(request: Request, db: Session) -> MetadataStatus:
    service = request.app.state.player_metadata
    count = lambda *where: db.scalar(select(func.count()).select_from(MusicAlbum).where(*where)) or 0  # noqa: E731
    return MetadataStatus(
        online_enabled=service.online_enabled(),
        contact_set=bool(request.app.state.settings.player_musicbrainz_contact),
        running=service.running,
        pending=service.pending(db),
        albums=count(),
        with_cover=count(MusicAlbum.cover_file.is_not(None)),
        found=count(MusicAlbum.meta_status == "found"),
        not_found=count(MusicAlbum.meta_status == "not_found"),
        errors=count(MusicAlbum.meta_status == "error"),
    )


@admin_router.get("/metadata", response_model=MetadataStatus)
def metadata_status(request: Request, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _metadata_status(request, db)


@admin_router.put("/metadata", response_model=MetadataStatus)
def metadata_switch(body: MetadataUpdate, request: Request, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    request.app.state.player_metadata.set_online(body.online_enabled)
    if body.online_enabled:
        request.app.state.player_metadata.start()
    return _metadata_status(request, db)


@admin_router.post("/metadata/run", response_model=MetadataStatus, status_code=status.HTTP_202_ACCEPTED)
def metadata_run(request: Request, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    request.app.state.player_metadata.start()
    return _metadata_status(request, db)


@admin_router.post("/metadata/retry", response_model=MetadataStatus, status_code=status.HTTP_202_ACCEPTED)
def metadata_retry(request: Request, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Looks up again the albums that were not found online, or failed."""
    for album in db.scalars(select(MusicAlbum).where(MusicAlbum.meta_status.in_(("not_found", "error")))):
        album.meta_status, album.meta_checked_at = "pending", None
    db.commit()
    request.app.state.player_metadata.start()
    return _metadata_status(request, db)


@admin_router.post("/albums/{album_id}/refresh", response_model=MetadataStatus, status_code=status.HTTP_202_ACCEPTED)
def refresh_album_info(album_id: int, request: Request, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Forgets the picture and the online data of one album and looks for them again."""
    album = db.get(MusicAlbum, album_id)
    if album is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Album not found")
    delete_covers(request.app.state.settings, album.id)
    album.cover_file, album.cover_source, album.cover_checked = None, None, False
    album.meta_status, album.meta_checked_at, album.mb_release_id = "pending", None, None
    db.commit()
    request.app.state.player_metadata.start()
    return _metadata_status(request, db)

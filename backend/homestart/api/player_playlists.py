"""Player: playlists of the users, and the content an administrator sets for the openpanel."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    PANEL_FAVORITES,
    PANEL_SUGGESTIONS,
    MusicAlbum,
    MusicSource,
    MusicTrack,
    PanelItem,
    Playlist,
    PlaylistTrack,
    User,
    ROLE_ADMIN,
)
from ..schemas import (
    PanelContent,
    PanelItemInput,
    PanelItemOut,
    PanelItemTitle,
    PanelOrder,
    PlaylistCreate,
    PlaylistDetail,
    PlaylistEntryOut,
    PlaylistOrder,
    PlaylistOut,
    PlaylistRename,
    TrackSelection,
)
from ..security import get_current_user, require_admin
from .player import _album_order, _live, _track_out

router = APIRouter(prefix="/api/player", tags=["player"])
admin_router = APIRouter(prefix="/api/config/player/panel", tags=["player"])

MAX_PLAYLISTS_PER_USER = 100
MAX_PLAYLIST_TRACKS = 2000
SELECTION_MAX = 5000


# --- access -------------------------------------------------------------------------


def visible_playlist(db: Session, user: User | None, playlist_id: int) -> Playlist:
    """A playlist of the user or a panel playlist (the only kind without a user); somebody else's is not shown to exist."""
    playlist = db.get(Playlist, playlist_id)
    if playlist is None or playlist.user_id not in ((None,) if user is None else (user.id, None)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist not found")
    return playlist


def can_edit(user: User, playlist: Playlist) -> bool:
    return playlist.user_id == user.id or (playlist.user_id is None and user.role == ROLE_ADMIN)


def editable_playlist(db: Session, user: User, playlist_id: int) -> Playlist:
    playlist = visible_playlist(db, user, playlist_id)
    if not can_edit(user, playlist):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an administrator can change a panel playlist")
    return playlist


# --- reading ------------------------------------------------------------------------


def _playable():
    """An entry can be played when its file is there and its location is switched on."""
    return and_(*_live())


def playlist_out(db: Session, playlist: Playlist, user: User | None) -> PlaylistOut:
    rows = db.execute(
        select(MusicTrack.duration_s, _playable())
        .select_from(PlaylistTrack)
        .join(MusicTrack, MusicTrack.id == PlaylistTrack.track_id)
        .where(PlaylistTrack.playlist_id == playlist.id)
    ).all()
    return PlaylistOut(
        id=playlist.id,
        name=playlist.name,
        panel=playlist.user_id is None,
        editable=bool(user and can_edit(user, playlist)),
        tracks=len(rows),
        playable=sum(1 for _, playable in rows if playable),
        duration_s=sum(duration or 0 for duration, playable in rows if playable),
    )


def playlist_track_ids(db: Session, playlist_id: int) -> list[int]:
    """The tracks of a playlist that can be played now, in the order of the list."""
    return list(
        db.scalars(
            select(PlaylistTrack.track_id)
            .join(MusicTrack, MusicTrack.id == PlaylistTrack.track_id)
            .where(PlaylistTrack.playlist_id == playlist_id, *_live())
            .order_by(PlaylistTrack.position, PlaylistTrack.id)
        )
    )


@router.get("/playlists", response_model=list[PlaylistOut])
def list_playlists(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The user's own playlists first, then the panel playlists, each by name."""
    rows = db.scalars(select(Playlist).where((Playlist.user_id == user.id) | Playlist.user_id.is_(None)))
    ordered = sorted(rows, key=lambda p: (p.user_id is None, p.name.casefold(), p.id))
    return [playlist_out(db, p, user) for p in ordered]


def playlist_detail(db: Session, user: User | None, playlist_id: int) -> PlaylistDetail:
    playlist = visible_playlist(db, user, playlist_id)
    rows = db.execute(
        select(PlaylistTrack.id, MusicTrack, MusicAlbum.title, MusicAlbum.cover_file, _playable())
        .join(MusicTrack, MusicTrack.id == PlaylistTrack.track_id)
        .outerjoin(MusicAlbum, MusicAlbum.id == MusicTrack.album_id)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position, PlaylistTrack.id)
    ).all()
    entries = [
        PlaylistEntryOut(**_track_out(track, title, cover).model_dump(), entry_id=entry_id, available=bool(playable))
        for entry_id, track, title, cover, playable in rows
    ]
    return PlaylistDetail(playlist=playlist_out(db, playlist, user), tracks=entries)


@router.get("/playlists/{playlist_id}", response_model=PlaylistDetail)
def get_playlist(playlist_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return playlist_detail(db, user, playlist_id)


# --- changing -----------------------------------------------------------------------


@router.post("/playlists", response_model=PlaylistOut, status_code=status.HTTP_201_CREATED)
def create_playlist(body: PlaylistCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.panel and user.role != ROLE_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an administrator can make a panel playlist")
    owner = None if body.panel else user.id
    if not body.panel and db.scalar(select(func.count()).select_from(Playlist).where(Playlist.user_id == user.id)) >= MAX_PLAYLISTS_PER_USER:
        raise HTTPException(status.HTTP_409_CONFLICT, f"You can have at most {MAX_PLAYLISTS_PER_USER} playlists")
    playlist = Playlist(user_id=owner, name=body.name)
    db.add(playlist)
    db.commit()
    return playlist_out(db, playlist, user)


@router.put("/playlists/{playlist_id}", response_model=PlaylistOut)
def rename_playlist(playlist_id: int, body: PlaylistRename, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    playlist = editable_playlist(db, user, playlist_id)
    playlist.name = body.name
    db.commit()
    return playlist_out(db, playlist, user)


@router.delete("/playlists/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_playlist(playlist_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    playlist = editable_playlist(db, user, playlist_id)
    # A panel playlist that was offered on the openpanel is taken off it too.
    db.execute(delete(PanelItem).where(PanelItem.kind == "playlist", PanelItem.ref == str(playlist.id)))
    db.delete(playlist)
    db.commit()


def selected_tracks(db: Session, user: User | None, body: TrackSelection) -> list[int]:
    """The ids of the tracks a selection names, in play order, only those a listener may play."""
    if body.track_id is not None:
        ids = db.scalars(select(MusicTrack.id).where(MusicTrack.id == body.track_id, *_live())).all()
    elif body.track_ids is not None:
        found = set(db.scalars(select(MusicTrack.id).where(MusicTrack.id.in_(body.track_ids), *_live())))
        ids = [i for i in body.track_ids if i in found]
    elif body.album_id is not None:
        ids = db.scalars(select(MusicTrack.id).where(MusicTrack.album_id == body.album_id, *_live()).order_by(*_album_order())).all()
    elif body.source_id is not None:
        path = (body.path or "").strip("/")
        query = select(MusicTrack.id).where(MusicTrack.source_id == body.source_id, *_live())
        if path:
            query = query.where((MusicTrack.folder == path) | MusicTrack.folder.startswith(f"{path}/", autoescape=True))
        ids = db.scalars(query.order_by(MusicTrack.folder, *_album_order()).limit(SELECTION_MAX)).all()
    elif body.playlist_id is not None:
        visible_playlist(db, user, body.playlist_id)
        ids = playlist_track_ids(db, body.playlist_id)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Say what to play")
    if not ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nothing to play")
    return list(ids)


@router.post("/playlists/{playlist_id}/tracks", response_model=PlaylistDetail)
def add_to_playlist(playlist_id: int, body: TrackSelection, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    playlist = editable_playlist(db, user, playlist_id)
    ids = selected_tracks(db, user, body)
    count = db.scalar(select(func.count()).select_from(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)) or 0
    if count + len(ids) > MAX_PLAYLIST_TRACKS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A playlist can hold at most {MAX_PLAYLIST_TRACKS} tracks")
    last = db.scalar(select(func.max(PlaylistTrack.position)).where(PlaylistTrack.playlist_id == playlist_id))
    start = -1 if last is None else last
    db.add_all(PlaylistTrack(playlist_id=playlist_id, track_id=track_id, position=start + n) for n, track_id in enumerate(ids, start=1))
    db.commit()
    return playlist_detail(db, user, playlist.id)


@router.delete("/playlists/{playlist_id}/tracks/{entry_id}", response_model=PlaylistDetail)
def remove_from_playlist(playlist_id: int, entry_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    playlist = editable_playlist(db, user, playlist_id)
    entry = db.get(PlaylistTrack, entry_id)
    if entry is None or entry.playlist_id != playlist_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    db.delete(entry)
    db.commit()
    return playlist_detail(db, user, playlist.id)


@router.put("/playlists/{playlist_id}/order", response_model=PlaylistDetail)
def reorder_playlist(playlist_id: int, body: PlaylistOrder, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    playlist = editable_playlist(db, user, playlist_id)
    entries = {e.id: e for e in db.scalars(select(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id))}
    if sorted(body.entry_ids) != sorted(entries):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The order must list every entry exactly once")
    for position, entry_id in enumerate(body.entry_ids):
        entries[entry_id].position = position
    db.commit()
    return playlist_detail(db, user, playlist.id)


# --- the openpanel content ------------------------------------------------------------


def _parse_folder(ref: str) -> tuple[int, str] | None:
    source_id, _, path = ref.partition(":")
    return (int(source_id), path.strip("/")) if source_id.isdigit() else None


def resolve_item(db: Session, item: PanelItem) -> tuple[str, bool]:
    """The name of an item and whether it can be played now."""
    if item.kind == "track":
        row = db.execute(select(MusicTrack.title, MusicTrack.artist, _playable()).where(MusicTrack.id == int(item.ref))).first() if item.ref.isdigit() else None
        return (f"{row[0]} – {row[1]}", bool(row[2])) if row else (item.ref, False)
    if item.kind == "album":
        album = db.get(MusicAlbum, int(item.ref)) if item.ref.isdigit() else None
        if album is None:
            return item.ref, False
        live = db.scalar(select(func.count()).select_from(MusicTrack).where(MusicTrack.album_id == album.id, *_live()))
        return f"{album.title} – {album.artist}", bool(live)
    if item.kind == "folder":
        parsed = _parse_folder(item.ref)
        source = db.get(MusicSource, parsed[0]) if parsed else None
        if source is None or parsed is None:
            return item.ref, False
        path = parsed[1]
        query = select(func.count()).select_from(MusicTrack).where(MusicTrack.source_id == source.id, *_live())
        if path:
            query = query.where((MusicTrack.folder == path) | MusicTrack.folder.startswith(f"{path}/", autoescape=True))
        return (f"{source.name}/{path}" if path else source.name), bool(db.scalar(query))
    playlist = db.get(Playlist, int(item.ref)) if item.ref.isdigit() else None
    if playlist is None or playlist.user_id is not None:
        return item.ref, False
    return playlist.name, bool(playlist_track_ids(db, playlist.id))


def item_selector(item: PanelItem) -> dict[str, int | str]:
    """What to send to the player to play the item."""
    if item.kind == "folder":
        parsed = _parse_folder(item.ref)
        return {"source_id": parsed[0], "path": parsed[1]} if parsed else {}
    key = {"track": "track_id", "album": "album_id", "playlist": "playlist_id"}[item.kind]
    return {key: int(item.ref)} if item.ref.isdigit() else {}


def _item_out(db: Session, item: PanelItem) -> PanelItemOut:
    name, available = resolve_item(db, item)
    return PanelItemOut(
        id=item.id,
        section=item.section,
        kind=item.kind,
        ref=item.ref,
        title=item.title,
        name=name,
        available=available,
        selector=item_selector(item),
        sort_order=item.sort_order,
    )


def panel_content(db: Session, user: User | None = None) -> PanelContent:
    """Everything the openpanel shows: favourites, suggestions and the panel playlists."""
    items = db.scalars(select(PanelItem).order_by(PanelItem.sort_order, PanelItem.id)).all()
    playlists = db.scalars(select(Playlist).where(Playlist.user_id.is_(None)))
    return PanelContent(
        favorites=[_item_out(db, i) for i in items if i.section == PANEL_FAVORITES],
        suggestions=[_item_out(db, i) for i in items if i.section == PANEL_SUGGESTIONS],
        playlists=[playlist_out(db, p, user) for p in sorted(playlists, key=lambda p: (p.name.casefold(), p.id))],
    )


@router.get("/panel", response_model=PanelContent)
def get_panel(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return panel_content(db, user)


def _check_item(db: Session, body: PanelItemInput) -> None:
    if body.section == PANEL_FAVORITES and body.kind != "track":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Favourites are tracks")
    if body.section == PANEL_SUGGESTIONS and body.kind == "track":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Suggestions are albums, folders or playlists")
    probe = PanelItem(section=body.section, kind=body.kind, ref=body.ref)
    if body.kind == "folder":
        parsed = _parse_folder(body.ref)
        if parsed is None or db.get(MusicSource, parsed[0]) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown location")
        probe.ref = f"{parsed[0]}:{parsed[1]}"
    elif not body.ref.isdigit():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown item")
    exists = {
        "track": lambda: db.get(MusicTrack, int(body.ref)),
        "album": lambda: db.get(MusicAlbum, int(body.ref)),
        "playlist": lambda: (p := db.get(Playlist, int(body.ref))) is not None and p.user_id is None,
        "folder": lambda: True,
    }[body.kind]()
    if not exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found (a playlist must be a panel playlist)")
    body.ref = probe.ref


@admin_router.post("/items", response_model=PanelItemOut, status_code=status.HTTP_201_CREATED)
def add_panel_item(body: PanelItemInput, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    _check_item(db, body)
    if db.scalar(select(PanelItem.id).where(PanelItem.section == body.section, PanelItem.kind == body.kind, PanelItem.ref == body.ref)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Already on the openpanel")
    last = db.scalar(select(func.max(PanelItem.sort_order)).where(PanelItem.section == body.section)) or 0
    item = PanelItem(section=body.section, kind=body.kind, ref=body.ref, title=body.title, sort_order=last + 1)
    db.add(item)
    db.commit()
    return _item_out(db, item)


def _get_item(db: Session, item_id: int) -> PanelItem:
    item = db.get(PanelItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return item


@admin_router.put("/items/{item_id}", response_model=PanelItemOut)
def retitle_panel_item(item_id: int, body: PanelItemTitle, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = _get_item(db, item_id)
    item.title = body.title
    db.commit()
    return _item_out(db, item)


@admin_router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_panel_item(item_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    db.delete(_get_item(db, item_id))
    db.commit()


@admin_router.put("/{section}/order", response_model=PanelContent)
def reorder_panel(section: str, body: PanelOrder, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if section not in (PANEL_FAVORITES, PANEL_SUGGESTIONS):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown section")
    items = {i.id: i for i in db.scalars(select(PanelItem).where(PanelItem.section == section))}
    if sorted(body.ids) != sorted(items):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The order must list every item exactly once")
    for position, item_id in enumerate(body.ids, start=1):
        items[item_id].sort_order = position
    db.commit()
    return panel_content(db, user)


@admin_router.get("", response_model=PanelContent)
def get_panel_for_admin(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return panel_content(db, user)

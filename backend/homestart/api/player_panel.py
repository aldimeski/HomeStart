"""Player on the openpanel: the library and the listening session for a tablet, without a login.

Open to the networks in [radio] allowed_networks (and to logged-in users), like the Radiopanel. A tablet is a listener of its
own: its session is the `client_id` it makes up, and nothing of it is tied to a user. It sees only what an old tablet can play.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..access import require_local_or_user
from ..db import get_db
from ..models import MusicSource, Playlist
from ..schemas import (
    CLIENT_ID_PATTERN,
    AlbumDetail,
    AlbumPage,
    FolderListing,
    GenreOut,
    LocationOut,
    PanelContent,
    PlayerCommand,
    PlayerState,
    PlaylistDetail,
    PlaylistOut,
    TrackPage,
)
from .player import (
    get_album,
    get_cover,
    list_albums,
    list_folder,
    list_genres,
    list_locations,
    list_tracks,
    visible_formats,
)
from .player_playlists import panel_content, playlist_detail, playlist_out
from .player_stream import SID_PATTERN, run_command, serve_track, session_state

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "X-HomeStart"


async def old_tablet_formats(request: Request) -> None:
    """Narrows what the rest of the request sees to the file types of [player] openpanel_formats.

    Async on purpose: it must run in the task that goes on to handle the request, for the setting to reach the handler.
    """
    visible_formats.set(request.app.state.settings.player_panel_formats)


async def require_custom_header(request: Request) -> None:
    # Pages of other sites cannot add this header, so a forged request cannot steer the player of a tablet.
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing header")


router = APIRouter(
    prefix="/openpanel/player",
    tags=["openpanel"],
    dependencies=[Depends(require_local_or_user), Depends(old_tablet_formats), Depends(require_custom_header)],
)

# The library is read exactly as in the app.
router.add_api_route("/albums", list_albums, methods=["GET"], response_model=AlbumPage)
router.add_api_route("/albums/{album_id}", get_album, methods=["GET"], response_model=AlbumDetail)
router.add_api_route("/genres", list_genres, methods=["GET"], response_model=list[GenreOut])
router.add_api_route("/tracks", list_tracks, methods=["GET"], response_model=TrackPage)
router.add_api_route("/locations", list_locations, methods=["GET"], response_model=list[LocationOut])
router.add_api_route("/folders", list_folder, methods=["GET"], response_model=FolderListing)
router.add_api_route("/cover/{album_id}", get_cover, methods=["GET"])


def _key(client_id: str) -> str:
    return f"panel:{client_id}"


@router.get("/content", response_model=PanelContent)
def content(db: Session = Depends(get_db)):
    """What the administrator put on the panel: favourites, suggestions and the panel playlists."""
    return panel_content(db)


@router.get("/playlists", response_model=list[PlaylistOut])
def playlists(db: Session = Depends(get_db)):
    rows = db.scalars(select(Playlist).where(Playlist.user_id.is_(None)))
    return [playlist_out(db, p, None) for p in sorted(rows, key=lambda p: (p.name.casefold(), p.id))]


@router.get("/playlists/{playlist_id}", response_model=PlaylistDetail)
def playlist(playlist_id: int, db: Session = Depends(get_db)):
    return playlist_detail(db, None, playlist_id)


@router.get("/session", response_model=PlayerState)
def get_state(request: Request, client_id: str = Query(pattern=CLIENT_ID_PATTERN), db: Session = Depends(get_db)):
    return session_state(request, db, _key(client_id))


@router.post("/session/command", response_model=PlayerState)
def command(body: PlayerCommand, request: Request, db: Session = Depends(get_db)):
    return run_command(request, db, _key(body.client_id), None, body)


@router.api_route("/stream/{track_id}", methods=["GET", "HEAD"])
async def stream(track_id: int, request: Request, sid: str = Query(default="default", pattern=SID_PATTERN)):
    return await serve_track(request, track_id, _key(sid))

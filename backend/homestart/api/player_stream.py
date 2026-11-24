"""Player: audio streams and the listening session (queue and controls) of each listener."""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..access import logged_in_user_id
from ..db import SessionLocal, get_db
from ..models import MusicAlbum, MusicSource, MusicTrack, User
from ..schemas import CLIENT_ID_PATTERN, PlayerCommand, PlayerState
from ..security import get_current_user
from ..services.player.files import CONTENT_TYPES, DEFAULT_CONTENT_TYPE, RangeNotSatisfiable, TrackFile, make_location, parse_range
from ..services.player.hub import HubFull, PlayerHub, Session as ListenSession
from .player import _live, _track_out, _track_query
from .player_playlists import selected_tracks

CHUNK = 64 * 1024
KEEPALIVE_SECONDS = 15

stream_router = APIRouter(tags=["player"])
router = APIRouter(prefix="/api/player/session", tags=["player"])

STREAM_HEADERS = {
    "Accept-Ranges": "bytes",
    "Cache-Control": "private, no-store",
    # Marks the audio as already encoded, so the gzip middleware leaves it alone.
    "Content-Encoding": "identity",
    "X-Accel-Buffering": "no",
}


def _hub(request: Request) -> PlayerHub:
    return request.app.state.player


def _session_key(user_id: int, client_id: str) -> str:
    return f"u{user_id}:{client_id}"


# --- audio ------------------------------------------------------------------------


def _open(request: Request, source: MusicSource, rel_path: str) -> TrackFile:
    return make_location(request.app.state.settings, request.app.state.secret_box, source).open_stream(rel_path)



async def _chunks(file: TrackFile, start: int, end: int, release) -> AsyncIterator[bytes]:
    try:
        position = start
        while position <= end:
            chunk = await run_in_threadpool(file.read, position, min(CHUNK, end - position + 1))
            if not chunk:
                break
            position += len(chunk)
            yield chunk
    finally:
        file.close()
        release()


SID_PATTERN = CLIENT_ID_PATTERN.replace("{8,64}", "{1,64}")


@stream_router.api_route("/player/stream/{track_id}", methods=["GET", "HEAD"])
async def stream_track(
    track_id: int,
    request: Request,
    sid: str = Query(default="default", pattern=SID_PATTERN),
    user_id: int = Depends(logged_in_user_id),
):
    return await serve_track(request, track_id, _session_key(user_id, sid))


async def serve_track(request: Request, track_id: int, key: str):
    """Sends a track to the listener of the session `key`; shared by the app and the openpanel."""
    # The database is only read here, briefly: the connection must not stay open for the length of the audio.
    with SessionLocal() as db:
        row = db.execute(
            select(MusicTrack.rel_path, MusicTrack.format, MusicSource)
            .join(MusicSource, MusicSource.id == MusicTrack.source_id)
            .where(MusicTrack.id == track_id, *_live())
        ).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Track not found")
        rel_path, fmt, source = row
        db.expunge(source)

    head = request.method == "HEAD"
    try:
        release = (lambda: None) if head else _hub(request).acquire_stream(key)
    except HubFull:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Too many listeners") from None

    try:
        file = await run_in_threadpool(_open, request, source, rel_path)
    except (OSError, ValueError):
        release()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The music file cannot be read") from None

    headers = dict(STREAM_HEADERS)
    try:
        wanted = parse_range(request.headers.get("range"), file.size)
    except RangeNotSatisfiable:
        file.close()
        release()
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{file.size}"})

    start, end = wanted if wanted else (0, file.size - 1)
    code = status.HTTP_206_PARTIAL_CONTENT if wanted else status.HTTP_200_OK
    if wanted:
        headers["Content-Range"] = f"bytes {start}-{end}/{file.size}"
    headers["Content-Length"] = str(max(end - start + 1, 0))
    media_type = CONTENT_TYPES.get(fmt, DEFAULT_CONTENT_TYPE)

    if head or file.size == 0:
        file.close()
        release()
        return Response(status_code=code, headers=headers, media_type=media_type)
    return StreamingResponse(
        _chunks(file, start, end, release),
        status_code=code,
        headers=headers,
        media_type=media_type,
        # The generator releases when the client leaves; this covers a response that never started.
        background=BackgroundTask(release),
    )


# --- the session ------------------------------------------------------------------


def _state(db: Session, session: ListenSession) -> PlayerState:
    """Builds the state for the listener; tracks that left the library are taken out of the queue first."""
    rows = {}
    if session.queue:
        rows = {
            row[0].id: row
            for row in db.execute(_track_query().where(MusicTrack.id.in_(set(session.queue))))
        }
        session.remove_ids(set(session.queue) - set(rows))
    return PlayerState(
        status=session.status,
        index=session.index,
        shuffle=session.shuffle,
        repeat=session.repeat,
        version=session.version,
        current_id=session.current_id,
        next_id=session.next_id,
        queue=[_track_out(*rows[i]) for i in session.queue],
    )


def _apply(db: Session, user: User | None, session: ListenSession, body: PlayerCommand) -> None:
    action = body.action
    if action == "play":
        if body.shuffle is not None:
            session.shuffle = body.shuffle
        session.play(selected_tracks(db, user, body), body.start_track_id)
    elif action in ("enqueue", "play_next"):
        ids = selected_tracks(db, user, body)
        if not session.queue:
            session.play(ids)
        elif action == "enqueue":
            session.enqueue(ids)
        else:
            session.play_next(ids)
    elif action == "pause":
        if session.status == "playing":
            session.status = "paused"
    elif action == "resume":
        if session.queue:
            session.status = "playing"
    elif action == "stop":
        session.status = "stopped" if session.queue else session.status
    elif action == "next":
        if session.queue:
            session.advance(1)
            session.errors = 0
    elif action == "prev":
        if session.queue:
            session.advance(-1)
            session.errors = 0
    elif action == "ended":
        if session.status == "playing":
            session.errors = 0
            session.advance(1)
    elif action == "error":
        if session.status == "playing":
            session.on_error()
    elif action == "jump":
        if body.index is None or body.index >= len(session.queue):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "There is no such place in the queue")
        session.index, session.status, session.errors = body.index, "playing", 0
    elif action == "shuffle":
        if body.on is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Say whether shuffle is on")
        session.set_shuffle(body.on)
    elif action == "repeat":
        if body.mode is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Say which repeat mode")
        session.repeat = body.mode
    elif action == "clear":
        session.clear()


def session_state(request: Request, db: Session, key: str) -> PlayerState:
    hub = _hub(request)
    try:
        with hub.lock:
            return _state(db, hub.session(key))
    except HubFull:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Too many listeners") from None


def run_command(request: Request, db: Session, key: str, user: User | None, body: PlayerCommand) -> PlayerState:
    """Applies a command to the session `key`; `user` is None on the openpanel."""
    hub = _hub(request)
    try:
        with hub.lock:
            session = hub.session(key)
            before = (session.status, session.index, session.queue[:], session.shuffle, session.repeat)
            _apply(db, user, session, body)
            state = _state(db, session)
            if before != (session.status, session.index, session.queue, session.shuffle, session.repeat):
                hub.changed(session)
                state.version = session.version
            return state
    except HubFull:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Too many listeners") from None


@router.get("", response_model=PlayerState)
def get_state(
    request: Request,
    client_id: str = Query(pattern=CLIENT_ID_PATTERN),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return session_state(request, db, _session_key(user.id, client_id))


@router.post("/command", response_model=PlayerState)
def command(body: PlayerCommand, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return run_command(request, db, _session_key(user.id, body.client_id), user, body)


@router.get("/events")
async def events(request: Request, client_id: str = Query(pattern=CLIENT_ID_PATTERN), user_id: int = Depends(logged_in_user_id)):
    """The state of the session as server-sent events: one at once, then one for every change."""
    hub = _hub(request)
    key = _session_key(user_id, client_id)

    def build() -> str:
        with SessionLocal() as db, hub.lock:
            return json.dumps(_state(db, hub.session(key)).model_dump())

    async def generate() -> AsyncIterator[str]:
        version = -1
        while not await request.is_disconnected():
            session = hub.session(key)
            if session.version != version:
                version = session.version
                yield f"data: {await run_in_threadpool(build)}\n\n"
                continue
            if not await hub.wait_for_change(session, version, KEEPALIVE_SECONDS):
                yield ": keepalive\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Content-Encoding": "identity"})

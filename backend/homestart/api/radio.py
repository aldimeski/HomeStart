"""Radiopanel: stations (administrators), and the open-in-the-local-network panel and audio relay."""

import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..access import require_local_or_user
from ..db import SessionLocal, get_db
from ..models import RadioStation, User
from ..schemas import RadioStationCreate, RadioStationOrder, RadioStationOut, RadioStationUpdate
from ..security import require_admin
from ..services.radio.hub import DEFAULT_CONTENT_TYPE, RadioError, StationSpec

PANEL_DIR = Path(__file__).resolve().parents[1] / "static" / "openpanel"
# Only these files are served from the panel folder.
PANEL_FILES = {
    "panel.js": "application/javascript",
    "panel.css": "text/css",
}
STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-store",
    # Marks the audio as already encoded, so the gzip middleware leaves it alone.
    "Content-Encoding": "identity",
    "X-Accel-Buffering": "no",
}

admin_router = APIRouter(prefix="/api/radio", tags=["radio"])
panel_router = APIRouter(prefix="/openpanel", tags=["openpanel"], dependencies=[Depends(require_local_or_user)])


def _station_out(station: RadioStation) -> RadioStationOut:
    return RadioStationOut(
        id=station.id,
        slug=station.slug,
        name=station.name,
        sub=station.sub,
        urls=json.loads(station.urls_json),
        content_type=station.content_type,
        sort_order=station.sort_order,
    )


def _get_station(db: Session, station_id: int) -> RadioStation:
    station = db.get(RadioStation, station_id)
    if station is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Station not found")
    return station


def _commit_unique(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Another station already uses this id") from None


@admin_router.get("/stations", response_model=list[RadioStationOut])
def list_stations(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [_station_out(s) for s in db.scalars(select(RadioStation).order_by(RadioStation.sort_order, RadioStation.id))]


@admin_router.post("/stations", response_model=RadioStationOut, status_code=status.HTTP_201_CREATED)
def create_station(body: RadioStationCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    station = RadioStation(
        slug=body.slug,
        name=body.name,
        sub=body.sub,
        urls_json=json.dumps(body.urls),
        content_type=body.content_type,
        sort_order=(db.scalar(select(func.max(RadioStation.sort_order))) or 0) + 1,
    )
    db.add(station)
    _commit_unique(db)
    return _station_out(station)


@admin_router.put("/stations/order", response_model=list[RadioStationOut])
def reorder_stations(body: RadioStationOrder, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    stations = {s.id: s for s in db.scalars(select(RadioStation))}
    if sorted(body.ids) != sorted(stations):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The order must list every station exactly once")
    for position, station_id in enumerate(body.ids, start=1):
        stations[station_id].sort_order = position
    db.commit()
    return [_station_out(stations[station_id]) for station_id in body.ids]


@admin_router.put("/stations/{station_id}", response_model=RadioStationOut)
def update_station(
    station_id: int, body: RadioStationUpdate, _: User = Depends(require_admin), db: Session = Depends(get_db)
):
    station = _get_station(db, station_id)
    station.slug = body.slug
    station.name = body.name
    station.sub = body.sub
    station.urls_json = json.dumps(body.urls)
    station.content_type = body.content_type
    _commit_unique(db)
    return _station_out(station)


@admin_router.delete("/stations/{station_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_station(station_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    db.delete(_get_station(db, station_id))
    db.commit()


# --- panel and audio, open to the local network -----------------------------------------------------------------


def _all_stations() -> list[RadioStation]:
    with SessionLocal() as db:
        return list(db.scalars(select(RadioStation).order_by(RadioStation.sort_order, RadioStation.id)))


def _station_spec(slug: str) -> StationSpec | None:
    with SessionLocal() as db:
        station = db.scalar(select(RadioStation).where(RadioStation.slug == slug))
        if station is None:
            return None
        return StationSpec(slug=station.slug, urls=tuple(json.loads(station.urls_json)), content_type=station.content_type)


@panel_router.get("", include_in_schema=False)
def panel_redirect():
    return RedirectResponse("/openpanel/")


@panel_router.get("/", include_in_schema=False)
def panel_page():
    return FileResponse(PANEL_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@panel_router.get("/health", include_in_schema=False)
def health():
    return Response("ok", media_type="text/plain")


@panel_router.get("/stations")
async def stations(request: Request):
    settings = request.app.state.settings
    rows = await run_in_threadpool(_all_stations)
    return {
        "openhab_enabled": bool(settings.openhab_url),
        "openhab_start": settings.openhab_start,
        "stations": [{"id": s.slug, "name": s.name, "sub": s.sub} for s in rows],
    }


@panel_router.get("/status")
async def status_report(request: Request):
    hub = request.app.state.radio
    rows = await run_in_threadpool(_all_stations)
    items = []
    for station in rows:
        listeners, title = hub.stream_info(station.slug)
        items.append({"id": station.slug, "name": station.name, "listeners": listeners, "title": title})
    return {
        "uptime_seconds": int(time.time() - hub.started_at),
        "total_listeners": hub.listener_count(),
        "max_listeners": hub.max_listeners,
        "stations": items,
    }


@panel_router.api_route("/radio/{slug}", methods=["GET", "HEAD"])
async def radio(slug: str, request: Request):
    spec = await run_in_threadpool(_station_spec, slug)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such station")
    try:
        listener, content_type = await request.app.state.radio.subscribe(spec)
    except RadioError as exc:
        raise HTTPException(exc.status_code, exc.message) from None

    if request.method == "HEAD":
        listener.close()
        return Response(status_code=200, media_type=content_type or DEFAULT_CONTENT_TYPE, headers=STREAM_HEADERS)
    # Safari may ask for a byte range first; the answer is always the whole live stream (200).
    return StreamingResponse(
        listener.chunks(), media_type=content_type, headers=STREAM_HEADERS, background=BackgroundTask(listener.close)
    )


@panel_router.get("/{filename}", include_in_schema=False)
def panel_file(filename: str):
    media_type = PANEL_FILES.get(filename)
    if media_type is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return FileResponse(PANEL_DIR / filename, media_type=media_type, headers={"Cache-Control": "no-cache"})

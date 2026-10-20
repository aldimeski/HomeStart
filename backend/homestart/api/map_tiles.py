"""Map tiles for the Škoda module, fetched by the server and cached on disk.

The browser only talks to HomeStart; the tile server sees one client (this server), and tiles that were
downloaded once are served from the cache for TILE_MAX_AGE.
"""

import asyncio
import logging
import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

from ..models import User
from ..security import get_current_user

log = logging.getLogger("homestart.map")

router = APIRouter(prefix="/api/map", tags=["map"])

MAX_ZOOM = 19
TILE_MAX_AGE_SECONDS = 30 * 24 * 3600
TILE_MAX_BYTES = 512 * 1024
# The OpenStreetMap tile policy requires an identifying User-Agent and few parallel requests.
USER_AGENT = "HomeStart/0.4 (self-hosted home portal)"
_downloads = asyncio.Semaphore(2)
# Requests go out over IPv4: httpx tries IPv6 first and waits about 5 s for it on networks without IPv6.
CACHE_HEADERS = {"Cache-Control": "private, max-age=604800"}


async def download_tile(url: str) -> bytes | None:
    async with _downloads:
        try:
            async with httpx.AsyncClient(
                timeout=10, headers={"User-Agent": USER_AGENT}, transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0")
            ) as http:
                response = await http.get(url)
        except httpx.HTTPError:
            return None
    content_type = response.headers.get("content-type", "")
    if response.status_code != 200 or not content_type.startswith("image/") or len(response.content) > TILE_MAX_BYTES:
        return None
    return response.content


@router.get("/tiles/{z}/{x}/{y}.png")
async def tile(z: int, x: int, y: int, request: Request, _: User = Depends(get_current_user)):
    if not 0 <= z <= MAX_ZOOM or not (0 <= x < 2**z and 0 <= y < 2**z):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such tile")
    settings = request.app.state.settings
    path: Path = settings.cache_dir / "tiles" / str(z) / str(x) / f"{y}.png"

    if path.is_file() and time.time() - path.stat().st_mtime < TILE_MAX_AGE_SECONDS:
        return FileResponse(path, media_type="image/png", headers=CACHE_HEADERS)

    content = await download_tile(settings.map_tile_url.format(z=z, x=x, y=y))
    if content is None:
        if path.is_file():  # an old tile is better than a hole in the map
            return FileResponse(path, media_type="image/png", headers=CACHE_HEADERS)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The map server did not answer")

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{y}.{uuid.uuid4().hex}.tmp")  # parallel requests for one tile must not mix
    temporary.write_bytes(content)
    temporary.replace(path)
    return FileResponse(path, media_type="image/png", headers=CACHE_HEADERS)

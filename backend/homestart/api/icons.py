import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import get_db
from ..models import Link, TasmotaDevice, User
from ..schemas import IconOut
from ..security import get_current_user, get_settings, require_admin
from ..services.svg_sanitizer import SvgError, sanitize_svg

router = APIRouter(prefix="/api/icons", tags=["icons"])

MAX_ICON_BYTES = 256 * 1024
ICON_FILE_PATTERN = re.compile(r"^[a-f0-9]{32}\.(svg|png|webp|ico)$")
MEDIA_TYPES = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "webp": "image/webp",
    "ico": "image/x-icon",
}


def _detect_format(data: bytes, filename: str) -> str:
    """Determines the image type from the file content; the extension alone is not trusted."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] == b"\x00\x00\x01\x00":
        return "ico"
    head = data[:1024].lstrip().lower()
    if filename.lower().endswith(".svg") or head.startswith(b"<svg") or head.startswith(b"<?xml"):
        return "svg"
    raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Supported formats: SVG, PNG, WebP, ICO")


def _icon_path(settings: Settings, name: str) -> Path:
    if not ICON_FILE_PATTERN.match(name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Icon not found")
    return settings.icons_dir / name


@router.get("", response_model=list[IconOut])
def list_uploaded_icons(_: User = Depends(require_admin), settings: Settings = Depends(get_settings)):
    files = sorted(
        (p for p in settings.icons_dir.iterdir() if ICON_FILE_PATTERN.match(p.name)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [IconOut(icon=f"upload:{p.name}") for p in files]


@router.post("", response_model=IconOut, status_code=status.HTTP_201_CREATED)
async def upload_icon(
    file: UploadFile,
    _: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
):
    data = await file.read(MAX_ICON_BYTES + 1)
    if len(data) > MAX_ICON_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Icon must be 256 KB or smaller")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty")

    fmt = _detect_format(data, file.filename or "")
    if fmt == "svg":
        try:
            data = sanitize_svg(data)
        except SvgError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    name = f"{uuid.uuid4().hex}.{fmt}"
    (settings.icons_dir / name).write_bytes(data)
    return IconOut(icon=f"upload:{name}")


@router.get("/{name}")
def get_icon(name: str, _: User = Depends(get_current_user), settings: Settings = Depends(get_settings)):
    path = _icon_path(settings, name)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Icon not found")
    return FileResponse(
        path,
        media_type=MEDIA_TYPES[path.suffix[1:]],
        headers={
            "Cache-Control": "private, max-age=86400",
            # Defence in depth: even a sanitized SVG opened directly cannot run scripts.
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        },
    )


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_icon(
    name: str,
    _: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    path = _icon_path(settings, name)
    reference = f"upload:{name}"
    if db.scalar(select(Link.id).where(Link.icon == reference)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The icon is used by a link")
    used_by_device = select(TasmotaDevice.id).where(
        (TasmotaDevice.icon == reference) | TasmotaDevice.relay_icons.contains(f'"{reference}"')
    )
    if db.scalar(used_by_device) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The icon is used by a TasmoSiz device or switch")
    path.unlink(missing_ok=True)

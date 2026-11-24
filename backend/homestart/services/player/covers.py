"""Album pictures: found in the files or the folders, checked and shrunk on the server, kept in the cache folder."""

import hashlib
import io
import logging
from pathlib import Path

import mutagen
from mutagen.id3 import ID3, ID3NoHeaderError
from PIL import Image, UnidentifiedImageError

from ...config import Settings

log = logging.getLogger("homestart.player")

SIZES = (96, 300, 600)
MAX_PIXELS = 40_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
JPEG_QUALITY = 85

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def covers_dir(settings: Settings) -> Path:
    directory = settings.cache_dir / "covers"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def normalize(data: bytes) -> bytes:
    """Checks that the bytes are a picture and returns it as a JPEG of at most the largest size. Raises ValueError."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ALLOWED_FORMATS:
                raise ValueError("Not a picture type that is accepted")
            if image.width < 16 or image.height < 16:
                raise ValueError("The picture is too small")
            picture = image.convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise ValueError("Not a usable picture") from exc
    picture.thumbnail((SIZES[-1], SIZES[-1]))
    out = io.BytesIO()
    picture.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()


def delete_covers(settings: Settings, album_id: int) -> None:
    for old in covers_dir(settings).glob(f"{album_id}-*.jpg"):
        old.unlink(missing_ok=True)


def save_cover(settings: Settings, album_id: int, data: bytes) -> str:
    """Stores the normalized picture and returns its file name (it changes with the picture, so browsers refetch it)."""
    jpeg = normalize(data)
    delete_covers(settings, album_id)
    name = f"{album_id}-{hashlib.sha1(jpeg).hexdigest()[:10]}.jpg"
    (covers_dir(settings) / name).write_bytes(jpeg)
    return name


def sized_cover(settings: Settings, name: str, size: int) -> Path:
    """The cover in one of the sizes; smaller ones are made on first use."""
    full = covers_dir(settings) / name
    if size >= SIZES[-1]:
        return full
    small = full.with_name(f"{full.stem}_{size}.jpg")
    if not small.exists():
        with Image.open(full) as image:
            image.thumbnail((size, size))
            image.save(small, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return small


def read_embedded(fileobj, fmt: str) -> bytes | None:
    """The picture stored inside a music file, if there is one."""
    try:
        if fmt == "mp3":
            try:
                frames = ID3(fileobj).getall("APIC")
            except ID3NoHeaderError:
                return None
            # The front cover (type 3) is preferred over any other picture.
            frames.sort(key=lambda f: f.type != 3)
            return bytes(frames[0].data) if frames else None
        file = mutagen.File(fileobj)
        if file is None:
            return None
        pictures = getattr(file, "pictures", None)  # FLAC
        if pictures:
            return bytes(pictures[0].data)
        covers = (file.tags or {}).get("covr") if fmt == "m4a" else None  # MP4
        return bytes(covers[0]) if covers else None
    except (mutagen.MutagenError, OSError, KeyError, IndexError):
        return None

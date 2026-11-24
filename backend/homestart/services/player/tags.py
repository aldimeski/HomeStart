"""Reads the tags of a music file, with the file and folder names as a fallback for what the tags do not have."""

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath

import mutagen
from mutagen.id3 import ID3, Encoding, ID3NoHeaderError
from mutagen.mp3 import MP3

log = logging.getLogger("homestart.player")

UNKNOWN_ARTIST = "Unknown artist"
UNKNOWN_ALBUM = "Unknown album"
VARIOUS_ARTISTS = "Various artists"

# "Artist - Album - 01 - Title", "Artist - 01 - Title" and "01 - Title", as music files are often named.
NAME_WITH_ALBUM = re.compile(r"^(?P<artist>.+?) - (?P<album>.+?) - (?P<no>\d{1,3}) - (?P<title>.+)$")
NAME_WITH_ARTIST = re.compile(r"^(?P<artist>.+?) - (?P<no>\d{1,3}) - (?P<title>.+)$")
NAME_WITH_NUMBER = re.compile(r"^(?P<no>\d{1,3})[ ._-]+(?P<title>.+)$")

# Letters that do not split into a base letter and an accent.
EXTRA_FOLDING = str.maketrans({"đ": "d", "ł": "l", "ø": "o", "ß": "ss", "æ": "ae", "œ": "oe"})


@dataclass
class TrackInfo:
    title: str
    artist: str
    album_artist: str | None
    album: str
    track_no: int | None
    disc_no: int | None
    year: int | None
    genre: str | None
    duration_s: float | None
    bitrate: int | None
    compilation: bool
    # The album name came from the folder because the tags have none.
    album_from_folder: bool
    derived: bool


def fold(text: str) -> str:
    """Lower case without accents, so that a search for "sto" finds "što"."""
    text = text.casefold().translate(EXTRA_FOLDING)
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def repair(text: str, legacy_encoding: str) -> str:
    """Fixes text that was stored in a legacy 8-bit encoding but declared as Latin-1 (what ID3v1 and many ID3v2.3 tags do)."""
    if text.isascii():
        return text
    try:
        raw = text.encode("latin-1")
    except UnicodeEncodeError:
        return text  # real Unicode already
    for encoding in ("utf-8", legacy_encoding):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return text


def _first_int(value: str | None) -> int | None:
    match = re.match(r"\s*(\d+)", value or "")
    return int(match.group(1)) if match else None


def _year(value: str | None) -> int | None:
    match = re.match(r"\s*(\d{4})", value or "")
    return int(match.group(1)) if match else None


def _clean(value: str | None) -> str | None:
    value = " ".join((value or "").split())
    return value or None


def _read_mp3(fileobj, legacy_encoding: str) -> dict:
    fields: dict = {}
    try:
        tags = ID3(fileobj)  # ID3v2, with ID3v1 as the fallback
    except ID3NoHeaderError:
        tags = None
    if tags is not None:

        def text(key: str) -> str | None:
            frame = tags.get(key)
            if frame is None or not frame.text:
                return None
            value = str(frame.text[0])
            return repair(value, legacy_encoding) if frame.encoding == Encoding.LATIN1 else value

        genre_frame = tags.get("TCON")
        genre = None
        if genre_frame is not None and genre_frame.genres:
            genre = repair(str(genre_frame.genres[0]), legacy_encoding) if genre_frame.encoding == Encoding.LATIN1 else str(genre_frame.genres[0])
        fields = {
            "title": text("TIT2"),
            "artist": text("TPE1"),
            "album_artist": text("TPE2"),
            "album": text("TALB"),
            "track": text("TRCK"),
            "disc": text("TPOS"),
            "date": text("TDRC") or text("TYER"),
            "genre": genre,
            "compilation": text("TCMP") == "1",
        }
    return fields


def _read_easy(fileobj) -> dict:
    easy = mutagen.File(fileobj, easy=True)
    if easy is None or easy.tags is None:
        return {}

    def text(key: str) -> str | None:
        values = easy.tags.get(key)
        return str(values[0]) if values else None

    return {
        "title": text("title"),
        "artist": text("artist"),
        "album_artist": text("albumartist"),
        "album": text("album"),
        "track": text("tracknumber"),
        "disc": text("discnumber"),
        "date": text("date"),
        "genre": text("genre"),
        "compilation": text("compilation") == "1",
    }


def read_track(fileobj, rel_path: str, fmt: str, legacy_encoding: str) -> TrackInfo:
    """Raises OSError when the file cannot be read; damaged tags only mean fewer fields."""
    fields: dict = {}
    duration = bitrate = None
    try:
        if fmt == "mp3":
            fields = _read_mp3(fileobj, legacy_encoding)
            info = MP3(fileobj).info
        else:
            fields = _read_easy(fileobj)
            fileobj.seek(0)
            info = mutagen.File(fileobj).info
        duration = float(info.length) if getattr(info, "length", None) else None
        bitrate = int(info.bitrate) if getattr(info, "bitrate", None) else None
    except (mutagen.MutagenError, AttributeError) as exc:  # AttributeError: not recognised as audio at all
        log.warning("Unreadable tags in %s: %s", rel_path, exc)

    posix = PurePosixPath(rel_path)
    stem = posix.stem
    folder_name = posix.parent.name
    from_name = {}
    for pattern in (NAME_WITH_ALBUM, NAME_WITH_ARTIST, NAME_WITH_NUMBER):
        match = pattern.match(stem)
        if match:
            from_name = match.groupdict()
            break

    derived = False
    title = _clean(fields.get("title"))
    if not title:
        title, derived = _clean(from_name.get("title")) or stem, True
    artist = _clean(fields.get("artist"))
    if not artist:
        artist, derived = _clean(from_name.get("artist")) or UNKNOWN_ARTIST, True
    album = _clean(fields.get("album"))
    album_from_folder = not album
    if not album:
        album, derived = folder_name or UNKNOWN_ALBUM, True

    return TrackInfo(
        title=title[:255],
        artist=artist[:255],
        album_artist=(_clean(fields.get("album_artist")) or "")[:255] or None,
        album=album[:255],
        track_no=_first_int(fields.get("track")) or _first_int(from_name.get("no")),
        disc_no=_first_int(fields.get("disc")),
        year=_year(fields.get("date")),
        genre=(_clean(fields.get("genre")) or "")[:128] or None,
        duration_s=duration,
        bitrate=bitrate,
        compilation=bool(fields.get("compilation")),
        album_from_folder=album_from_folder,
        derived=derived,
    )

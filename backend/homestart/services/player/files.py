"""The music locations: a folder of the server or an SMB share, read through one interface.

Only this module turns a library entry into a path or a network address, and only it holds the credentials of a share
in the clear (decrypted for the length of a call).
"""

import ipaddress
import os
import re
import socket
import threading
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import smbclient
from smbprotocol import exceptions as smb_exceptions

from ...config import Settings
from ...models import SOURCE_LOCAL, SOURCE_SMB, MusicSource
from ..secret_box import SecretBox

CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
}
DEFAULT_CONTENT_TYPE = "application/octet-stream"

HOST_PATTERN = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]{0,253}[A-Za-z0-9])?$")
SHARE_FORBIDDEN = re.compile(r'[\\/:*?"<>|]')
SMB_PORT = 445

# NtStatus codes of the answers worth a clear message.
STATUS_MESSAGES = {
    0xC000006D: "Wrong user name or password",
    0xC000006E: "Wrong user name or password",
    0xC0000022: "Access denied: this user is not allowed to read the share",
    0xC00000CC: "The share does not exist on the server",
    0xC0000034: "The folder does not exist on the share",
    0xC000003A: "The folder does not exist on the share",
    0xC0000225: "The folder does not exist on the share",
    0xC000009A: "The server has no resources for another connection",
}


class LocationError(OSError):
    """A location cannot be reached or read; the message is fit for the administrator to read (no secrets in it)."""


def smb_error(exc: BaseException) -> LocationError:
    status = getattr(exc, "ntstatus", None) or getattr(exc, "status", None)
    if isinstance(status, int) and status in STATUS_MESSAGES:
        return LocationError(STATUS_MESSAGES[status])
    if isinstance(exc, smb_exceptions.LogonFailure):
        return LocationError(STATUS_MESSAGES[0xC000006D])
    if isinstance(exc, smb_exceptions.AccessDenied):
        return LocationError(STATUS_MESSAGES[0xC0000022])
    if isinstance(exc, smb_exceptions.BadNetworkName):
        return LocationError(STATUS_MESSAGES[0xC00000CC])
    if isinstance(exc, (TimeoutError, ConnectionError, socket.gaierror, smb_exceptions.SMBConnectionClosed)):
        return LocationError("Cannot reach the server")
    if isinstance(exc, (FileNotFoundError, NotADirectoryError)):
        return LocationError("The folder does not exist on the share")
    return LocationError("The server answered with an error")


def parse_network_path(text: str) -> tuple[str, str, str]:
    r"""Splits \\server\share\folder (also //server/share/folder and smb://server/share/folder) into its three parts."""
    text = text.strip()
    if text.lower().startswith("smb://"):
        text = text[6:]
    parts = [part for part in re.split(r"[\\/]+", text) if part]
    if len(parts) < 2:
        raise ValueError(r"Enter the network path like \\server\share or \\server\share\folder")
    host, share, folders = parts[0], parts[1], parts[2:]
    if not HOST_PATTERN.match(host):
        raise ValueError("The server name is not valid")
    if SHARE_FORBIDDEN.search(share) or share in (".", ".."):
        raise ValueError("The share name is not valid")
    if any(part in (".", "..") or part.endswith(" ") or SHARE_FORBIDDEN.search(part) for part in folders):
        raise ValueError("The folder is not valid")
    return host, share, "/".join(folders)


def check_private_host(host: str) -> None:
    """Only servers of the local network are allowed, so the function cannot be used to reach other addresses."""
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, SMB_PORT, type=socket.SOCK_STREAM)}
        except OSError:
            raise LocationError("The server name cannot be found") from None
    if not all(a.is_private or a.is_loopback or a.is_link_local for a in addresses):
        raise LocationError("Only servers of the local network are allowed")


class TrackFile:
    """A file opened for reading at any offset."""

    def __init__(self, handle: BinaryIO, size: int, on_error: Callable[[BaseException], OSError] | None = None):
        self._handle = handle
        self.size = size
        self._on_error = on_error

    def read(self, offset: int, length: int) -> bytes:
        try:
            self._handle.seek(offset)
            return self._handle.read(length)
        except OSError as exc:
            raise (self._on_error(exc) if self._on_error else exc) from None

    def close(self) -> None:
        try:
            self._handle.close()
        except OSError:
            pass


class _Reader:
    """What the tag reader gets: a read-only file with a name, whatever the file is opened from."""

    def __init__(self, handle: BinaryIO, name: str):
        self._handle = handle
        self.name = name
        self.read = handle.read
        self.seek = handle.seek
        self.tell = handle.tell

    def close(self) -> None:
        self._handle.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


MAX_IMAGE_BYTES = 10 * 1024 * 1024
FOLDER_IMAGE_STEMS = ("cover", "folder", "front", "albumart", "album")
FOLDER_IMAGE_EXTENSIONS = ("jpg", "jpeg", "png")


def pick_folder_image(names: list[str]) -> str | None:
    """The file of a folder that is most likely the album picture (cover.jpg, folder.jpg, front.png ...)."""
    best = None
    for name in names:
        stem, _, extension = name.rpartition(".")
        if stem.lower() in FOLDER_IMAGE_STEMS and extension.lower() in FOLDER_IMAGE_EXTENSIONS:
            rank = (FOLDER_IMAGE_STEMS.index(stem.lower()), FOLDER_IMAGE_EXTENSIONS.index(extension.lower()))
            if best is None or rank < best[0]:
                best = (rank, name)
    return best[1] if best else None


def _read_limited(handle: BinaryIO) -> bytes | None:
    data = handle.read(MAX_IMAGE_BYTES + 1)
    return data if len(data) <= MAX_IMAGE_BYTES else None


Found = dict[str, tuple[int, int, str]]  # {relative path: (size, modification time, format)}


class Location:
    """A music location. Relative paths always use "/", whatever the location is."""

    def check(self) -> None:
        raise NotImplementedError

    def walk(self, formats: tuple[str, ...], cancel: threading.Event, on_error: Callable[[OSError], None], limit: int | None = None) -> Found:
        raise NotImplementedError

    def open_for_tags(self, rel_path: str) -> _Reader:
        raise NotImplementedError

    def open_stream(self, rel_path: str) -> TrackFile:
        raise NotImplementedError

    def read_folder_image(self, folder: str) -> bytes | None:
        """The album picture lying in a folder of the location, if there is one."""
        raise NotImplementedError


class WalkCancelled(Exception):
    pass


class LocalLocation(Location):
    def __init__(self, path: str):
        self.root = path

    def check(self) -> None:
        if not os.path.isdir(self.root) or not os.access(self.root, os.R_OK | os.X_OK):
            raise LocationError("The folder does not exist or cannot be read")

    def walk(self, formats, cancel, on_error, limit=None) -> Found:
        found: Found = {}
        root_real = os.path.realpath(self.root)
        for current, dirs, files in os.walk(self.root, followlinks=False, onerror=on_error):
            if cancel.is_set():
                raise WalkCancelled
            dirs.sort()
            for name in files:
                extension = name.rpartition(".")[2].lower()
                if extension not in formats:
                    continue
                full = os.path.join(current, name)
                try:
                    # A link that leads out of the location is skipped.
                    if os.path.islink(full) and not os.path.realpath(full).startswith(root_real + os.sep):
                        continue
                    stat = os.stat(full)
                except OSError as exc:
                    on_error(exc)
                    continue
                rel = PurePosixPath(*os.path.relpath(full, self.root).split(os.sep)).as_posix()
                found[rel] = (stat.st_size, int(stat.st_mtime), extension)
                if limit and len(found) >= limit:
                    return found
        return found

    def _full(self, rel_path: str) -> Path:
        root = Path(self.root).resolve()
        full = root.joinpath(*rel_path.split("/")).resolve()
        # The path comes from the database, but a link inside the location may still lead elsewhere.
        if not full.is_relative_to(root) or not full.is_file():
            raise LocationError("The file is not there")
        return full

    def open_for_tags(self, rel_path: str) -> _Reader:
        return _Reader(self._full(rel_path).open("rb"), rel_path)

    def open_stream(self, rel_path: str) -> TrackFile:
        handle = self._full(rel_path).open("rb")
        return TrackFile(handle, os.fstat(handle.fileno()).st_size)

    def read_folder_image(self, folder: str) -> bytes | None:
        try:
            root = Path(self.root).resolve()
            directory = root.joinpath(*[p for p in folder.split("/") if p]).resolve()
            if not directory.is_relative_to(root) or not directory.is_dir():
                return None
            name = pick_folder_image([e.name for e in os.scandir(directory) if e.is_file()])
            if name is None:
                return None
            rel = f"{folder}/{name}" if folder else name
            with self._full(rel).open("rb") as handle:
                return _read_limited(handle)
        except OSError:
            return None


class SmbLocation(Location):
    def __init__(self, host: str, share: str, subpath: str, username: str, password: str, timeout: int):
        base = rf"\\{host}\{share}"
        self.root = "\\".join([base, *[p for p in subpath.split("/") if p]])
        self.host = host
        # With no user name the share is read as a guest.
        self._options = dict(
            username=username or "Guest",
            password=password if username else "",
            port=SMB_PORT,
            auth_protocol="ntlm",
            connection_timeout=timeout,
        )

    def _path(self, rel_path: str) -> str:
        return "\\".join([self.root, *rel_path.split("/")])

    def check(self) -> None:
        check_private_host(self.host)
        try:
            with smbclient.scandir(self.root, **self._options):
                pass
        except Exception as exc:  # noqa: BLE001 - everything the library raises becomes a readable message
            raise smb_error(exc) from None

    def walk(self, formats, cancel, on_error, limit=None) -> Found:
        found: Found = {}
        pending = [("", self.root)]
        while pending:
            if cancel.is_set():
                raise WalkCancelled
            rel_dir, path = pending.pop()
            try:
                with smbclient.scandir(path, **self._options) as entries:
                    listing = sorted(entries, key=lambda e: e.name)
                    subdirs = []
                    for entry in listing:
                        if entry.is_symlink():
                            continue  # a link may lead anywhere
                        rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                        if entry.is_dir():
                            subdirs.append((rel, f"{path}\\{entry.name}"))
                            continue
                        extension = entry.name.rpartition(".")[2].lower()
                        if extension not in formats:
                            continue
                        stat = entry.stat()
                        found[rel] = (stat.st_size, int(stat.st_mtime), extension)
                        if limit and len(found) >= limit:
                            return found
                    pending.extend(reversed(subdirs))
            except Exception as exc:  # noqa: BLE001
                error = smb_error(exc)
                if not rel_dir:
                    raise error from None  # the location itself cannot be read: the scan fails
                on_error(OSError(f"{rel_dir}: {error}"))
        return found

    def open_for_tags(self, rel_path: str) -> _Reader:
        try:
            return _Reader(smbclient.open_file(self._path(rel_path), mode="rb", **self._options), rel_path)
        except Exception as exc:  # noqa: BLE001
            raise smb_error(exc) from None

    def open_stream(self, rel_path: str) -> TrackFile:
        path = self._path(rel_path)
        try:
            size = smbclient.stat(path, **self._options).st_size
            handle = smbclient.open_file(path, mode="rb", **self._options)
        except Exception as exc:  # noqa: BLE001
            raise smb_error(exc) from None
        return TrackFile(handle, size, smb_error)

    def read_folder_image(self, folder: str) -> bytes | None:
        directory = self._path(folder) if folder else self.root
        try:
            with smbclient.scandir(directory, **self._options) as entries:
                name = pick_folder_image([e.name for e in entries if not e.is_dir() and not e.is_symlink()])
            if name is None:
                return None
            with smbclient.open_file(f"{directory}\\{name}", mode="rb", **self._options) as handle:
                return _read_limited(handle)
        except Exception:  # noqa: BLE001 - a picture is a nicety; the library works without it
            return None


def make_location(settings: Settings, secret_box: SecretBox, source: MusicSource) -> Location:
    if source.kind == SOURCE_LOCAL and source.path:
        return LocalLocation(source.path)
    if source.kind == SOURCE_SMB and source.host and source.share:
        username = secret_box.decrypt(source.username_enc) if source.username_enc else ""
        password = secret_box.decrypt(source.password_enc) if source.password_enc else ""
        return SmbLocation(source.host, source.share, source.subpath or "", username, password, settings.player_smb_timeout)
    raise ValueError("This location is not set up correctly")


def reset_connections() -> None:
    """Drops the open connections to shares, e.g. after a password was changed."""
    smbclient.reset_connection_cache()


class RangeNotSatisfiable(Exception):
    pass


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """The (first, last) byte of a Range request, None when the whole file is wanted.

    Only a single byte range is honoured; anything else is answered with the whole file, as the standard allows.
    """
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    first, _, last = header[6:].strip().partition("-")
    try:
        if first == "":
            length = int(last)  # the last N bytes
            if length <= 0:
                raise RangeNotSatisfiable
            return max(size - length, 0), size - 1
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        return None
    if start >= size or end < start:
        raise RangeNotSatisfiable
    return start, min(end, size - 1)

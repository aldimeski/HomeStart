import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .services.player.files import parse_network_path

USERNAME_PATTERN = r"^[A-Za-z0-9._-]{1,64}$"
ICON_PATTERN = re.compile(r"^(mdi:[a-z0-9-]{1,100}|builtin:[a-z0-9-]{1,64}|upload:[a-f0-9]{32}\.(svg|png|webp|ico))$")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    theme: Literal["system", "light", "dark"]
    sidebar_collapsed: bool
    sholink_expanded: bool


class SettingsUpdate(BaseModel):
    theme: Literal["system", "light", "dark"] | None = None
    sidebar_collapsed: bool | None = None
    sholink_expanded: bool | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Literal["admin", "user"]
    is_active: bool
    created_at: datetime
    last_login: datetime | None


class MeOut(BaseModel):
    user: UserOut
    settings: SettingsOut


class UserCreate(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(max_length=256)
    role: Literal["admin", "user"] = "user"
    is_active: bool = True


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, pattern=USERNAME_PATTERN)
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    new_password: str = Field(max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


def _validate_url(value: str) -> str:
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("URL must start with http:// or https:// and contain a host")
    if parts.username or parts.password:
        raise ValueError("URL must not contain credentials")
    return value


def _validate_icon(value: str) -> str:
    if not ICON_PATTERN.match(value):
        raise ValueError("Invalid icon reference")
    return value


class LinkBase(BaseModel):
    title: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=1, max_length=2048)
    icon: str = "mdi:link-variant"
    open_in_new_tab: bool = False

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title must not be empty")
        return value

    _url = field_validator("url")(_validate_url)
    _icon = field_validator("icon")(_validate_icon)


class LinkCreate(LinkBase):
    pass


class LinkUpdate(LinkBase):
    pass


class LinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    url: str
    icon: str
    open_in_new_tab: bool
    sort_order: int


class LinkOrder(BaseModel):
    ids: list[int]


class EmbedCheck(BaseModel):
    reachable: bool
    embeddable: bool | None
    reason: str | None = None


class IconOut(BaseModel):
    icon: str


RADIO_SLUG_PATTERN = r"^[a-z0-9-]{1,40}$"
CONTENT_TYPE_PATTERN = r"^[a-z0-9.+-]+/[a-z0-9.+-]+$"


class RadioStationBase(BaseModel):
    slug: str = Field(pattern=RADIO_SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=64)
    sub: str | None = Field(default=None, max_length=64)
    urls: list[str] = Field(min_length=1, max_length=5)
    content_type: str | None = Field(default=None, max_length=64, pattern=CONTENT_TYPE_PATTERN)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name must not be empty")
        return value

    @field_validator("sub", "content_type")
    @classmethod
    def _empty_to_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("urls")
    @classmethod
    def _check_urls(cls, values: list[str]) -> list[str]:
        cleaned = [_validate_url(value) for value in values]
        if any(len(value) > 500 for value in cleaned):
            raise ValueError("A source address is too long")
        return cleaned


class RadioStationCreate(RadioStationBase):
    pass


class RadioStationUpdate(RadioStationBase):
    pass


class RadioStationOut(BaseModel):
    id: int
    slug: str
    name: str
    sub: str | None
    urls: list[str]
    content_type: str | None
    sort_order: int


class RadioStationOrder(BaseModel):
    ids: list[int]


class MusicSourceInput(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: Literal["local", "smb"] = "local"
    path: str | None = Field(default=None, max_length=1000)  # local folder
    network_path: str | None = Field(default=None, max_length=1000)  # \\server\\share\\folder
    username: str | None = Field(default=None, max_length=128)
    # Never sent back. When editing, leaving it out keeps the saved one.
    password: str | None = Field(default=None, max_length=256)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name must not be empty")
        return value

    @field_validator("path", "network_path", "username")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @model_validator(mode="after")
    def _check_kind(self):
        if self.kind == "local":
            if not self.path:
                raise ValueError("Enter the folder on the server")
        else:
            if not self.network_path:
                raise ValueError("Enter the network path")
            parse_network_path(self.network_path)  # raises ValueError with a message
        return self


class MusicSourceTestInput(MusicSourceInput):
    # The saved location whose password is used when none is typed.
    source_id: int | None = None


class MusicSourceTestResult(BaseModel):
    ok: bool
    message: str
    tracks: int | None = None


class MusicSourceOut(BaseModel):
    id: int
    name: str
    kind: str
    path: str | None
    network_path: str | None
    username: str | None
    has_password: bool
    enabled: bool
    last_scan_at: datetime | None
    last_scan_status: str | None
    tracks: int
    missing: int


class MusicScanOut(BaseModel):
    id: int
    source_id: int
    started_at: datetime
    finished_at: datetime | None
    started_by: str | None  # the user name, or null when the schedule started it
    status: str
    added: int
    changed: int
    removed: int
    errors: int
    error_message: str | None


class MusicScanDetail(MusicScanOut):
    added_files: list[str]
    changed_files: list[str]
    removed_files: list[str]
    new_folders: list[str]
    removed_folders: list[str]
    error_list: list[str]


class MusicScanStarted(BaseModel):
    scan_id: int
    sources: int


class MusicScanStatus(BaseModel):
    scanning: bool
    scan_id: int | None


class TrackOut(BaseModel):
    id: int
    title: str
    artist: str
    album_id: int | None
    album: str | None
    track_no: int | None
    disc_no: int | None
    year: int | None
    genre: str | None
    duration_s: float | None
    format: str
    has_cover: bool


class TrackPage(BaseModel):
    items: list[TrackOut]
    total: int


class AlbumOut(BaseModel):
    id: int
    title: str
    artist: str
    year: int | None
    genre: str | None
    tracks: int
    duration_s: float
    has_cover: bool


class AlbumPage(BaseModel):
    items: list[AlbumOut]
    total: int


class AlbumDetail(BaseModel):
    album: AlbumOut
    tracks: list[TrackOut]


class GenreOut(BaseModel):
    name: str | None  # null = tracks without a genre
    tracks: int
    albums: int


class LocationOut(BaseModel):
    id: int
    name: str
    tracks: int


class FolderEntry(BaseModel):
    name: str
    path: str
    tracks: int  # including the subfolders


class FolderListing(BaseModel):
    source_id: int
    source_name: str
    path: str
    folders: list[FolderEntry]
    tracks: list[TrackOut]


CLIENT_ID_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


class TrackSelection(BaseModel):
    """What to play or add: one track, several, an album, a folder with everything below it, or a playlist."""

    track_id: int | None = None
    track_ids: list[int] | None = Field(default=None, max_length=500)
    album_id: int | None = None
    source_id: int | None = None
    path: str | None = Field(default=None, max_length=1000)
    playlist_id: int | None = None


class PlayerCommand(TrackSelection):
    client_id: str = Field(pattern=CLIENT_ID_PATTERN)
    action: Literal[
        "play", "enqueue", "play_next", "pause", "resume", "stop", "next", "prev", "ended", "error", "jump", "shuffle", "repeat", "clear"
    ]
    # Where in the new queue to start (a track of it); with "shuffle" the queue is shuffled from the start.
    start_track_id: int | None = None
    shuffle: bool | None = None
    index: int | None = Field(default=None, ge=0)
    on: bool | None = None
    mode: Literal["off", "all", "one"] | None = None


class PlayerState(BaseModel):
    status: Literal["stopped", "playing", "paused"]
    index: int
    shuffle: bool
    repeat: Literal["off", "all", "one"]
    version: int
    current_id: int | None
    next_id: int | None
    queue: list[TrackOut]


class MetadataStatus(BaseModel):
    online_enabled: bool
    contact_set: bool
    running: bool
    pending: int  # albums still waiting for a picture or an online lookup
    albums: int
    with_cover: int
    found: int
    not_found: int
    errors: int


class MetadataUpdate(BaseModel):
    online_enabled: bool


class PlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    panel: bool = False  # a playlist for the openpanel (administrators)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name must not be empty")
        return value


class PlaylistRename(BaseModel):
    name: str = Field(min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name must not be empty")
        return value


class PlaylistOut(BaseModel):
    id: int
    name: str
    panel: bool
    editable: bool
    tracks: int
    playable: int  # entries that can be played now
    duration_s: float


class PlaylistEntryOut(TrackOut):
    entry_id: int
    available: bool


class PlaylistDetail(BaseModel):
    playlist: PlaylistOut
    tracks: list[PlaylistEntryOut]


class PlaylistOrder(BaseModel):
    entry_ids: list[int]


class PanelItemInput(BaseModel):
    section: Literal["favorites", "suggestions"]
    kind: Literal["track", "album", "folder", "playlist"]
    ref: str = Field(min_length=1, max_length=1100)
    title: str | None = Field(default=None, max_length=64)

    @field_validator("title")
    @classmethod
    def _empty_to_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class PanelItemTitle(BaseModel):
    title: str | None = Field(default=None, max_length=64)

    @field_validator("title")
    @classmethod
    def _empty_to_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class PanelItemOut(BaseModel):
    id: int
    section: str
    kind: str
    ref: str
    title: str | None
    name: str  # what the item is called, when no title is set
    available: bool
    selector: dict[str, int | str]  # what to give the player to play the item
    sort_order: int


class PanelContent(BaseModel):
    favorites: list[PanelItemOut]
    suggestions: list[PanelItemOut]
    playlists: list[PlaylistOut]


class PanelOrder(BaseModel):
    ids: list[int]

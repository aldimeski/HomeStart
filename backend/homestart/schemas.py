import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

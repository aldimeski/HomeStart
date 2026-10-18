"""Loads application settings from homestart.ini or homestart_default.ini."""

import configparser
import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("homestart.config")

USER_INI_NAME = "homestart.ini"
DEFAULT_INI_NAME = "homestart_default.ini"

DEFAULT_INI_CONTENT = """\
# HomeStart default settings.
# This file is created by the application and may be overwritten on upgrade.
# Do not edit it: copy it to homestart.ini and change the copy instead.
# Relative paths are resolved against the application folder.

[database]
file = data/homestart.db

[server]
host = 0.0.0.0
port = 8000

[security]
# Session expires after this many minutes of inactivity.
session_timeout_minutes = 480
# Failed logins (per username and IP) before a temporary lockout.
max_failed_logins = 5
lockout_minutes = 15

[storage]
icons_dir = data/icons
"""


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    app_dir: Path
    ini_file: Path
    db_file: Path
    host: str
    port: int
    session_timeout_minutes: int
    max_failed_logins: int
    lockout_minutes: int
    icons_dir: Path
    frontend_dir: Path


def default_app_dir() -> Path:
    env_home = os.environ.get("HOMESTART_HOME")
    if env_home:
        return Path(env_home).resolve()
    return Path(__file__).resolve().parents[2]


def _resolve(app_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (app_dir / path).resolve()


def _get_int(parser: configparser.ConfigParser, section: str, key: str, fallback: int, ini: Path) -> int:
    try:
        value = parser.getint(section, key, fallback=fallback)
    except ValueError as exc:
        raise ConfigError(f"{ini}: [{section}] {key} must be an integer") from exc
    if value <= 0:
        raise ConfigError(f"{ini}: [{section}] {key} must be greater than zero")
    return value


def load_settings(app_dir: Path | None = None) -> Settings:
    app_dir = app_dir or default_app_dir()
    user_ini = app_dir / USER_INI_NAME
    default_ini = app_dir / DEFAULT_INI_NAME

    if user_ini.exists():
        ini_file = user_ini
    else:
        if not default_ini.exists():
            default_ini.write_text(DEFAULT_INI_CONTENT, encoding="utf-8")
            log.info("Created %s", default_ini)
        ini_file = default_ini

    parser = configparser.ConfigParser()
    try:
        with ini_file.open(encoding="utf-8") as fh:
            parser.read_file(fh)
    except (configparser.Error, OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Cannot read {ini_file}: {exc}") from exc

    if not parser.has_section("database"):
        raise ConfigError(f"{ini_file}: missing required section [database]")
    db_value = parser.get("database", "file", fallback="").strip()
    if not db_value:
        raise ConfigError(f"{ini_file}: [database] file is not set")

    port = _get_int(parser, "server", "port", 8000, ini_file)
    if port > 65535:
        raise ConfigError(f"{ini_file}: [server] port is out of range")

    settings = Settings(
        app_dir=app_dir,
        ini_file=ini_file,
        db_file=_resolve(app_dir, db_value),
        host=parser.get("server", "host", fallback="0.0.0.0").strip(),
        port=port,
        session_timeout_minutes=_get_int(parser, "security", "session_timeout_minutes", 480, ini_file),
        max_failed_logins=_get_int(parser, "security", "max_failed_logins", 5, ini_file),
        lockout_minutes=_get_int(parser, "security", "lockout_minutes", 15, ini_file),
        icons_dir=_resolve(app_dir, parser.get("storage", "icons_dir", fallback="data/icons")),
        frontend_dir=app_dir / "frontend" / "dist",
    )
    log.info("Loaded settings from %s", ini_file)
    log.info("Database file: %s", settings.db_file)
    return settings


def prepare_directories(settings: Settings) -> None:
    for directory in (settings.db_file.parent, settings.icons_dir):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigError(f"Cannot create directory {directory}: {exc}") from exc
        if not os.access(directory, os.W_OK):
            raise ConfigError(f"Directory {directory} is not writable")
    if settings.db_file.exists() and not os.access(settings.db_file, os.W_OK):
        raise ConfigError(f"Database file {settings.db_file} is not writable")

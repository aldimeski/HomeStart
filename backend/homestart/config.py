"""Loads application settings from homestart.ini or homestart_default.ini."""

import configparser
import ipaddress
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
# Key for encrypting stored device credentials. Keep it outside the database folder on a server.
key_file = data/homestart.key

[storage]
icons_dir = data/icons
# Downloaded vehicle images and map tiles; can be deleted at any time.
cache_dir = data/cache

[mqtt]
enabled = true
host = localhost
port = 1883

[network]
# Subnet for "Scan network" (TasmoSiz). Empty = the server's own /24 network.
scan_subnet =

[map]
# Map tiles for the Škoda module, fetched by the server and cached in cache_dir.
tile_url = https://tile.openstreetmap.org/{z}/{x}/{y}.png

[backup]
# Database copies made by "python -m homestart.backup" (homestart-backup.timer runs it daily).
dir = data/backups
# Daily copies of the last N days.
daily_keep = 7
# Monthly copies (the first copy of each month, normally made on the 1st) of the last N months.
monthly_keep = 5
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
    key_file: Path
    mqtt_enabled: bool
    mqtt_host: str
    mqtt_port: int
    scan_subnet: ipaddress.IPv4Network | None
    cache_dir: Path
    map_tile_url: str
    backup_dir: Path
    backup_daily_keep: int
    backup_monthly_keep: int


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
        # The default file belongs to the application and is refreshed when a new version changes it.
        if not default_ini.exists() or default_ini.read_text(encoding="utf-8") != DEFAULT_INI_CONTENT:
            default_ini.write_text(DEFAULT_INI_CONTENT, encoding="utf-8")
            log.info("Wrote %s", default_ini)
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

    mqtt_port = _get_int(parser, "mqtt", "port", 1883, ini_file)
    try:
        mqtt_enabled = parser.getboolean("mqtt", "enabled", fallback=True)
    except ValueError as exc:
        raise ConfigError(f"{ini_file}: [mqtt] enabled must be true or false") from exc

    subnet_value = parser.get("network", "scan_subnet", fallback="").strip()
    scan_subnet = None
    if subnet_value:
        try:
            scan_subnet = ipaddress.IPv4Network(subnet_value, strict=False)
        except ValueError as exc:
            raise ConfigError(f"{ini_file}: [network] scan_subnet is not a valid IPv4 network") from exc
        if scan_subnet.num_addresses > 1024 or not scan_subnet.is_private:
            raise ConfigError(f"{ini_file}: [network] scan_subnet must be a private network of at most /22")

    tile_url = parser.get("map", "tile_url", fallback="https://tile.openstreetmap.org/{z}/{x}/{y}.png").strip()
    if not tile_url.startswith("https://") or not all(part in tile_url for part in ("{z}", "{x}", "{y}")):
        raise ConfigError(f"{ini_file}: [map] tile_url must be an https URL containing {{z}}, {{x}} and {{y}}")

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
        key_file=_resolve(app_dir, parser.get("security", "key_file", fallback="data/homestart.key")),
        mqtt_enabled=mqtt_enabled,
        mqtt_host=parser.get("mqtt", "host", fallback="localhost").strip(),
        mqtt_port=mqtt_port,
        scan_subnet=scan_subnet,
        cache_dir=_resolve(app_dir, parser.get("storage", "cache_dir", fallback="data/cache")),
        map_tile_url=tile_url,
        backup_dir=_resolve(app_dir, parser.get("backup", "dir", fallback="data/backups")),
        backup_daily_keep=_get_int(parser, "backup", "daily_keep", 7, ini_file),
        backup_monthly_keep=_get_int(parser, "backup", "monthly_keep", 5, ini_file),
    )
    log.info("Loaded settings from %s", ini_file)
    log.info("Database file: %s", settings.db_file)
    return settings


def prepare_directories(settings: Settings) -> None:
    for directory in (settings.db_file.parent, settings.icons_dir, settings.cache_dir):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigError(f"Cannot create directory {directory}: {exc}") from exc
        if not os.access(directory, os.W_OK):
            raise ConfigError(f"Directory {directory} is not writable")
    if settings.db_file.exists() and not os.access(settings.db_file, os.W_OK):
        raise ConfigError(f"Database file {settings.db_file} is not writable")

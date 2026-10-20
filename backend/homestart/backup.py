"""Database backup: python -m homestart.backup (homestart-backup.timer runs it once a day).

Each run makes a daily copy, and the first copy of a month (normally the one made on the 1st) is also kept as
the monthly copy. Daily copies are kept for [backup] daily_keep days, monthly copies for monthly_keep months:

    <dir>/daily/homestart-2026-10-20.db
    <dir>/monthly/homestart-2026-10.db

The copy is made with SQLite's backup API, so it is consistent while HomeStart keeps running.
"""

import logging
import os
import re
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from .config import ConfigError, Settings, load_settings

log = logging.getLogger("homestart.backup")

DAILY_NAME = re.compile(r"^homestart-(\d{4}-\d{2}-\d{2})\.db$")
MONTHLY_NAME = re.compile(r"^homestart-(\d{4}-\d{2})\.db$")


class BackupError(Exception):
    pass


def _copy_database(source: Path, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        # closing(): a sqlite3 connection used as a context manager only commits, it stays open.
        with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(temporary)) as dst:
            src.backup(dst)
            # The copy inherits WAL mode; a single self-contained file is what a backup should be.
            dst.execute("PRAGMA journal_mode=DELETE")
            result = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise BackupError(f"The copy failed the integrity check: {result}")
        # The copy holds password hashes and encrypted logins, so only the service account may read it.
        os.chmod(temporary, 0o600)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _prune(folder: Path, pattern: re.Pattern, keep: set[str]) -> list[str]:
    removed = []
    for path in sorted(folder.iterdir()):
        match = pattern.match(path.name)
        if match and match.group(1) not in keep:
            path.unlink()
            removed.append(path.name)
    return removed


def run_backup(settings: Settings, today: date | None = None) -> Path:
    today = today or date.today()
    if not settings.db_file.is_file():
        raise BackupError(f"Database {settings.db_file} does not exist")

    daily_dir = settings.backup_dir / "daily"
    monthly_dir = settings.backup_dir / "monthly"
    for folder in (settings.backup_dir, daily_dir, monthly_dir):
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)

    daily = daily_dir / f"homestart-{today:%Y-%m-%d}.db"
    _copy_database(settings.db_file, daily)
    log.info("Database copied to %s", daily)

    monthly = monthly_dir / f"homestart-{today:%Y-%m}.db"
    if not monthly.exists():
        shutil.copy2(daily, monthly)
        log.info("Monthly copy %s", monthly)

    keep_days = {f"{today - timedelta(days=n):%Y-%m-%d}" for n in range(settings.backup_daily_keep)}
    months = sorted((m.group(1) for p in monthly_dir.iterdir() if (m := MONTHLY_NAME.match(p.name))), reverse=True)
    removed = _prune(daily_dir, DAILY_NAME, keep_days) + _prune(
        monthly_dir, MONTHLY_NAME, set(months[: settings.backup_monthly_keep])
    )
    if removed:
        log.info("Removed old copies: %s", ", ".join(removed))
    return daily


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    try:
        run_backup(load_settings())
    except (ConfigError, BackupError, OSError, sqlite3.Error) as exc:
        log.error("Backup failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

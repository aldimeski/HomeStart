import sqlite3
import stat
from datetime import date, timedelta

import pytest

from homestart.backup import BackupError, main, run_backup
from homestart.config import load_settings


@pytest.fixture
def settings(tmp_path):
    (tmp_path / "homestart.ini").write_text("[database]\nfile = data/test.db\n[backup]\ndir = data/backups\n")
    (tmp_path / "data").mkdir()
    with sqlite3.connect(tmp_path / "data" / "test.db") as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE t (v TEXT)")
        db.execute("INSERT INTO t VALUES ('first')")
    return load_settings(tmp_path)


def names(folder):
    return sorted(path.name for path in folder.iterdir())


def test_copy_is_a_readable_database_only_for_the_owner(settings):
    copy = run_backup(settings, date(2026, 10, 20))
    # A single self-contained file: no WAL or temporary files next to it.
    assert names(settings.backup_dir / "daily") == ["homestart-2026-10-20.db"]
    with sqlite3.connect(copy) as db:
        assert db.execute("SELECT v FROM t").fetchall() == [("first",)]
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600
    assert stat.S_IMODE((settings.backup_dir / "daily").stat().st_mode) == 0o700
    # The first copy of a month is also the monthly copy.
    assert names(settings.backup_dir / "monthly") == ["homestart-2026-10.db"]


def test_retention_keeps_seven_days_and_five_months(settings):
    day = date(2026, 3, 15)
    while day <= date(2026, 10, 20):
        run_backup(settings, day)
        day += timedelta(days=1)

    assert names(settings.backup_dir / "daily") == [f"homestart-2026-10-{d:02d}.db" for d in range(14, 21)]
    assert names(settings.backup_dir / "monthly") == [f"homestart-2026-{m:02d}.db" for m in range(6, 11)]


def test_monthly_copy_is_the_one_made_on_the_first(settings):
    with sqlite3.connect(settings.db_file) as db:
        db.execute("UPDATE t SET v = 'on the 1st'")
    run_backup(settings, date(2026, 11, 1))
    with sqlite3.connect(settings.db_file) as db:
        db.execute("UPDATE t SET v = 'later'")
    run_backup(settings, date(2026, 11, 2))

    with sqlite3.connect(settings.backup_dir / "monthly" / "homestart-2026-11.db") as db:
        assert db.execute("SELECT v FROM t").fetchone() == ("on the 1st",)


def test_server_off_on_the_first_still_gets_a_monthly_copy(settings):
    run_backup(settings, date(2026, 12, 3))  # the timer catches up after the server was off
    assert names(settings.backup_dir / "monthly") == ["homestart-2026-12.db"]


def test_missing_database_fails_with_exit_code(settings, monkeypatch, tmp_path):
    settings.db_file.unlink()
    with pytest.raises(BackupError):
        run_backup(settings)
    monkeypatch.setenv("HOMESTART_HOME", str(tmp_path))
    assert main() == 1

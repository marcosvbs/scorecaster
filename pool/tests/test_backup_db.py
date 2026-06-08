import sqlite3

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.fixture
def db_file(tmp_path, monkeypatch):
    """A real on-disk SQLite file the command can back up.

    monkeypatch.setitem swaps only the NAME entry and restores it precisely,
    without Django's "overriding DATABASES" warning.
    """
    path = tmp_path / "db.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE marker (value TEXT)")
    conn.execute("INSERT INTO marker VALUES ('original')")
    conn.commit()
    conn.close()
    monkeypatch.setitem(settings.DATABASES["default"], "NAME", str(path))
    return path


def read_marker(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT value FROM marker").fetchone()[0]
    finally:
        conn.close()


def test_creates_backup(db_file):
    call_command("backup_db")

    backup = db_file.parent / "db.sqlite3.bak.1"
    assert backup.exists()
    assert read_marker(backup) == "original"


def test_rotates_and_keeps_three(db_file):
    for run in range(5):
        conn = sqlite3.connect(db_file)
        conn.execute("UPDATE marker SET value = ?", (f"run-{run}",))
        conn.commit()
        conn.close()
        call_command("backup_db")

    names = sorted(p.name for p in db_file.parent.glob("db.sqlite3.bak.*"))
    assert names == ["db.sqlite3.bak.1", "db.sqlite3.bak.2", "db.sqlite3.bak.3"]
    # Newest backup holds the latest data, oldest kept copy lags by 2 runs.
    assert read_marker(db_file.parent / "db.sqlite3.bak.1") == "run-4"
    assert read_marker(db_file.parent / "db.sqlite3.bak.3") == "run-2"


def test_missing_database_raises(tmp_path, monkeypatch):
    monkeypatch.setitem(
        settings.DATABASES["default"], "NAME", str(tmp_path / "nope.sqlite3")
    )

    with pytest.raises(CommandError):
        call_command("backup_db")

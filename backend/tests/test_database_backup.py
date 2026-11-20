from pathlib import Path
import sqlite3

import pytest

from app.operations.backup import create_backup, restore_backup, verify_backup


def make_database(path, value="original"):
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS sample (value TEXT NOT NULL)")
        connection.execute("DELETE FROM sample")
        connection.execute("INSERT INTO sample(value) VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def read_value(path):
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT value FROM sample").fetchone()[0]


def test_online_backup_is_verified_and_contains_rows(tmp_path):
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backups" / "snapshot.sqlite3"
    make_database(source)

    result = create_backup(source, backup)

    assert result["status"] == "verified"
    assert result["integrity_check"] == "ok"
    assert result["tables"]["sample"] == 1
    assert read_value(backup) == "original"
    assert verify_backup(backup)["sha256"] == result["sha256"]


def test_backup_refuses_source_as_destination(tmp_path):
    source = tmp_path / "source.sqlite3"
    make_database(source)

    with pytest.raises(ValueError, match="must differ"):
        create_backup(source, source)


def test_restore_refuses_overwrite_without_explicit_flag(tmp_path):
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    destination = tmp_path / "destination.sqlite3"
    make_database(source, "backup")
    create_backup(source, backup)
    make_database(destination, "existing")

    with pytest.raises(FileExistsError):
        restore_backup(backup, destination)

    assert read_value(destination) == "existing"


def test_restore_is_atomic_and_preserves_pre_restore_backup(tmp_path):
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    destination = tmp_path / "destination.sqlite3"
    make_database(source, "restored")
    create_backup(source, backup)
    make_database(destination, "pre-restore")
    Path(str(destination) + "-wal").write_bytes(b"stale wal")
    Path(str(destination) + "-shm").write_bytes(b"stale shm")

    result = restore_backup(backup, destination, replace=True)
    assert not Path(str(destination) + "-wal").exists()
    assert not Path(str(destination) + "-shm").exists()

    assert result["status"] == "restored"
    assert result["integrity_check"] == "ok"
    assert read_value(destination) == "restored"
    assert result["pre_restore_backup"]["status"] == "verified"
    assert read_value(result["pre_restore_backup"]["path"]) == "pre-restore"


def test_verify_rejects_non_sqlite_file(tmp_path):
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_text("not a database")

    with pytest.raises(ValueError, match="not a readable SQLite"):
        verify_backup(corrupt)

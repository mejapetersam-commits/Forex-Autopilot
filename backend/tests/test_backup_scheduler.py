import sqlite3
from datetime import datetime, timezone
from app.operations.backup_scheduler import run_backup_cycle, write_worker_heartbeat

def make_db(path):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS sample (value TEXT)")
        db.execute("INSERT INTO sample VALUES ('current')")

def test_scheduler_creates_backup_and_prunes_only_expired_verified_snapshots(tmp_path):
    source = tmp_path / "source.sqlite3"
    make_db(source)
    directory = tmp_path / "backups"
    directory.mkdir()
    old = directory / "telemetry-20260101T000000Z.sqlite3"
    with sqlite3.connect(old) as db:
        db.execute("CREATE TABLE sample (value TEXT)")
        db.execute("INSERT INTO sample VALUES ('old')")
    unrelated = directory / "notes.sqlite3"
    unrelated.write_text("keep")
    result = run_backup_cycle(source, directory, retention_days=30,
                              now=datetime(2026, 11, 19, tzinfo=timezone.utc))
    assert result["backup"]["status"] == "verified"
    assert result["removed"] == [old.name]
    assert not old.exists()
    assert unrelated.read_text() == "keep"

def test_scheduler_keeps_corrupt_expired_snapshots(tmp_path):
    source = tmp_path / "source.sqlite3"
    make_db(source)
    directory = tmp_path / "backups"
    directory.mkdir()
    corrupt = directory / "telemetry-20260101T000000Z.sqlite3"
    corrupt.write_text("not sqlite")
    result = run_backup_cycle(source, directory, retention_days=30,
                              now=datetime(2026, 11, 19, tzinfo=timezone.utc))
    assert result["removed"] == []
    assert corrupt.exists()

def test_scheduler_rejects_naive_timestamp_and_invalid_retention(tmp_path):
    source = tmp_path / "source.sqlite3"
    make_db(source)
    try:
        run_backup_cycle(source, tmp_path / "backups", now=datetime(2026, 11, 19))
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive timestamps must fail")



def test_worker_heartbeat_is_atomic_and_records_last_verified_backup(tmp_path):
    import json

    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    result = write_worker_heartbeat(
        tmp_path, now=now, backup_name="telemetry-20261120T120000Z.sqlite3"
    )
    heartbeat = json.loads((tmp_path / "backup-worker-heartbeat.json").read_text())
    assert result == heartbeat
    assert heartbeat["status"] == "ok"
    assert heartbeat["observed_at"] == now.isoformat()
    assert heartbeat["backup"] == "telemetry-20261120T120000Z.sqlite3"
    assert not (tmp_path / "backup-worker-heartbeat.json.tmp").exists()


def test_worker_heartbeat_rejects_naive_timestamp(tmp_path):
    try:
        write_worker_heartbeat(tmp_path, now=datetime(2026, 11, 20))
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive heartbeat time must fail")

"""Consistent SQLite backup, verification and controlled restore utilities.

Backups use SQLite's online backup API, so committed WAL contents are included.
Restore is intentionally an offline operation: stop the API before replacing its
database file. This module never starts or enables trading.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup(path: str | Path) -> dict[str, Any]:
    """Verify SQLite integrity and return a compact, non-sensitive manifest."""
    backup_path = Path(path).expanduser().resolve()
    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        raise ValueError(f"Backup file is missing or empty: {backup_path}")
    try:
        connection = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
        try:
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            integrity = [row[0] for row in integrity_rows]
            if integrity != ["ok"]:
                raise ValueError(f"SQLite integrity check failed: {integrity[:10]}")
            tables = [
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
            counts = {
                table: int(connection.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0])
                for table in tables
            }
            return {
                "status": "verified",
                "path": str(backup_path),
                "size_bytes": backup_path.stat().st_size,
                "sha256": _sha256(backup_path),
                "integrity_check": "ok",
                "tables": counts,
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"Backup is not a readable SQLite database: {exc}") from exc


def create_backup(source: str | Path, destination: str | Path) -> dict[str, Any]:
    """Create a transactionally consistent SQLite backup and verify it."""
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if source_path == destination_path:
        raise ValueError("Backup destination must differ from the source database.")
    if not source_path.is_file():
        raise FileNotFoundError(f"Source database does not exist: {source_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination_path.name}.", suffix=".tmp",
        dir=str(destination_path.parent),
    )
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        source_connection = sqlite3.connect(
            f"file:{source_path}?mode=ro", uri=True, timeout=30
        )
        destination_connection = sqlite3.connect(temporary_path, timeout=30)
        try:
            source_connection.backup(destination_connection, pages=256, sleep=0.05)
        finally:
            destination_connection.close()
            source_connection.close()
        manifest = verify_backup(temporary_path)
        os.replace(temporary_path, destination_path)
        manifest["path"] = str(destination_path)
        manifest["sha256"] = _sha256(destination_path)
        manifest["size_bytes"] = destination_path.stat().st_size
        return manifest
    finally:
        temporary_path.unlink(missing_ok=True)


def restore_backup(
    backup: str | Path,
    destination: str | Path,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    """Restore a verified backup atomically; refuse overwrite unless explicit."""
    backup_path = Path(backup).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if backup_path == destination_path:
        raise ValueError("Backup and restore destination must differ.")
    source_manifest = verify_backup(backup_path)
    if destination_path.exists() and not replace:
        raise FileExistsError(
            "Restore destination exists. Pass replace=True only after stopping the API."
        )
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    pre_restore = None
    if destination_path.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        pre_restore_path = destination_path.with_name(
            f"{destination_path.name}.pre-restore-{timestamp}.bak"
        )
        pre_restore = create_backup(destination_path, pre_restore_path)

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination_path.name}.", suffix=".restore",
        dir=str(destination_path.parent),
    )
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        source_connection = sqlite3.connect(
            f"file:{backup_path}?mode=ro", uri=True, timeout=30
        )
        destination_connection = sqlite3.connect(temporary_path, timeout=30)
        try:
            source_connection.backup(destination_connection, pages=256, sleep=0.05)
        finally:
            destination_connection.close()
            source_connection.close()
        restored_manifest = verify_backup(temporary_path)
        # A stale WAL/SHM pair belongs to the previous database and must not be
        # replayed against the restored snapshot. Restore is an offline operation.
        Path(str(destination_path) + "-wal").unlink(missing_ok=True)
        Path(str(destination_path) + "-shm").unlink(missing_ok=True)
        os.replace(temporary_path, destination_path)
        return {
            "status": "restored",
            "destination": str(destination_path),
            "source_sha256": source_manifest["sha256"],
            "restored_sha256": _sha256(destination_path),
            "integrity_check": restored_manifest["integrity_check"],
            "pre_restore_backup": pre_restore,
        }
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="FOREX AUTOPILOT SQLite maintenance")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--source", required=True)
    backup_parser.add_argument("--destination", required=True)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--backup", required=True)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup", required=True)
    restore_parser.add_argument("--destination", required=True)
    restore_parser.add_argument("--replace", action="store_true")

    args = parser.parse_args()
    if args.command == "backup":
        result = create_backup(args.source, args.destination)
    elif args.command == "verify":
        result = verify_backup(args.backup)
    else:
        result = restore_backup(
            args.backup, args.destination, replace=args.replace
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

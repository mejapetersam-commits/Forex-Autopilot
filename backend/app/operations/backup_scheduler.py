"""Scheduled local SQLite backups with bounded retention."""
from __future__ import annotations
import logging, os, re, signal, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app.operations.backup import create_backup, verify_backup

_LOG = logging.getLogger("forex_autopilot.backup_scheduler")
_NAME = re.compile(r"^telemetry-\d{8}T\d{6}Z\.sqlite3$")

def run_backup_cycle(source, backup_dir, *, retention_days=30, now=None):
    if retention_days < 1 or retention_days > 3650:
        raise ValueError("retention_days must be between 1 and 3650.")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Backup scheduler timestamps must be timezone-aware.")
    current = current.astimezone(timezone.utc)
    directory = Path(backup_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"telemetry-{current.strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
    manifest = create_backup(source, destination)
    cutoff = current - timedelta(days=retention_days)
    removed = []
    for candidate in directory.iterdir():
        if not candidate.is_file() or not _NAME.fullmatch(candidate.name):
            continue
        try:
            stamp = datetime.strptime(candidate.stem.removeprefix("telemetry-"), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if stamp >= cutoff or candidate == destination:
            continue
        try:
            verify_backup(candidate)
        except (ValueError, OSError):
            _LOG.exception("Keeping invalid old backup %s", candidate)
            continue
        candidate.unlink()
        removed.append(candidate.name)
    return {"backup": manifest, "retention_days": retention_days, "removed": removed}

def main():
    logging.basicConfig(level=os.getenv("BACKUP_LOG_LEVEL", "INFO"))
    source = Path(os.getenv("FOREX_AUTOPILOT_TELEMETRY_DB", "/var/lib/forex-autopilot/telemetry.sqlite3"))
    backup_dir = Path(os.getenv("FOREX_AUTOPILOT_BACKUP_DIR", "/var/backups/forex-autopilot"))
    interval = int(os.getenv("FOREX_AUTOPILOT_BACKUP_INTERVAL_SECONDS", "86400"))
    retention = int(os.getenv("FOREX_AUTOPILOT_BACKUP_RETENTION_DAYS", "30"))
    if interval < 3600 or interval > 604800:
        raise ValueError("Backup interval must be between 1 hour and 7 days.")
    stopping = False
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        succeeded = False
        try:
            result = run_backup_cycle(source, backup_dir, retention_days=retention)
            _LOG.info("Verified backup %s (%s bytes); pruned %s snapshots",
                      result["backup"]["path"], result["backup"]["size_bytes"], len(result["removed"]))
            succeeded = True
        except Exception:
            _LOG.exception("Scheduled backup failed; retrying soon.")
        # Retry failures promptly; never wait a full daily interval after startup
        # races, temporary database unavailability or a transient I/O error.
        remaining = interval if succeeded else min(300, interval)
        while remaining > 0 and not stopping:
            step = min(remaining, 30)
            time.sleep(step)
            remaining -= step

if __name__ == "__main__":
    main()

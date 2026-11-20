"""Periodic read-only telemetry health checks that persist operator events."""
from __future__ import annotations
import json, logging, os, signal, time
from datetime import datetime, timezone
from app.market_data.telemetry_store import TelemetryStore
from app.monitoring.health import assess_system_health
from app.operations.event_outbox import EventOutbox

_LOG = logging.getLogger("forex_autopilot.health_monitor")

def assess_backup_worker(now=None) -> tuple[dict[str, object], list[dict[str, str]]]:
    """Assess the backup worker heartbeat stored on the shared telemetry volume."""
    from pathlib import Path

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Backup worker assessment time must be timezone-aware.")
    database = os.getenv(
        "FOREX_AUTOPILOT_TELEMETRY_DB", "data/telemetry.sqlite3"
    )
    heartbeat_path = Path(database).expanduser().parent / "backup-worker-heartbeat.json"
    interval = max(3600, int(os.getenv(
        "FOREX_AUTOPILOT_BACKUP_INTERVAL_SECONDS", "86400"
    )))
    max_age = max(7200, interval * 2 + 300)
    try:
        heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        observed = datetime.fromisoformat(
            str(heartbeat["observed_at"]).replace("Z", "+00:00")
        )
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("Heartbeat timestamp must be timezone-aware.")
        age = (current.astimezone(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
        if heartbeat.get("status") != "ok" or age < -300 or age > max_age:
            raise ValueError("Backup worker heartbeat is stale or invalid.")
        return {
            "status": "healthy", "fresh": True,
            "age_seconds": round(max(0.0, age), 1),
            "last_backup": heartbeat.get("backup"),
        }, []
    except FileNotFoundError:
        message = "No backup worker heartbeat has been recorded."
        code = "BACKUP_WORKER_HEARTBEAT_MISSING"
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        message = "Backup worker heartbeat is invalid or stale."
        code = "BACKUP_WORKER_HEARTBEAT_STALE"
    return {
        "status": "attention_required", "fresh": False,
        "age_seconds": None, "last_backup": None,
    }, [{"code": code, "severity": "critical", "message": message}]


def run_health_monitor_cycle(*, now=None) -> dict[str, object]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Health monitor time must be timezone-aware.")
    current = current.astimezone(timezone.utc)
    store = TelemetryStore()
    stale_after = max(5, int(os.getenv("FOREX_AUTOPILOT_TELEMETRY_STALE_AFTER_SECONDS", "60")))
    health = assess_system_health(
        store.latest_heartbeat(), store.latest_account(), store.latest_quotes(),
        stale_after_seconds=stale_after, now=current,
    )
    backup_worker, backup_alerts = assess_backup_worker(current)
    alerts = list(health["alerts"]) + backup_alerts
    outbox = EventOutbox()
    transitions = outbox.reconcile_health_alerts(alerts, now=current)
    return {
        "health_status": "critical" if backup_alerts else health["status"],
        "backup_worker": backup_worker,
        "alerts_detected": len(alerts),
        "events_recorded": transitions["alerts_created"],
        "events_resolved": transitions["alerts_resolved"],
        "alerts_still_active": transitions["alerts_still_active"],
        "assessed_at": health["assessed_at"],
    }

def main():
    logging.basicConfig(level=os.getenv("HEALTH_MONITOR_LOG_LEVEL", "INFO"))
    interval = int(os.getenv("FOREX_AUTOPILOT_HEALTH_MONITOR_INTERVAL_SECONDS", "30"))
    if interval < 5 or interval > 300:
        raise ValueError("Health monitor interval must be between 5 and 300 seconds.")
    stopping = False
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        try:
            result = run_health_monitor_cycle()
            _LOG.info("Health=%s alerts=%s", result["health_status"], result["alerts_detected"])
        except Exception:
            _LOG.exception("Health monitor cycle failed.")
        remaining = interval
        while remaining > 0 and not stopping:
            step = min(remaining, 5)
            time.sleep(step)
            remaining -= step

if __name__ == "__main__":
    main()

"""Periodic read-only telemetry health checks that persist operator events."""
from __future__ import annotations
import logging, os, signal, time
from datetime import datetime, timezone
from app.market_data.telemetry_store import TelemetryStore
from app.monitoring.health import assess_system_health
from app.operations.event_outbox import EventOutbox

_LOG = logging.getLogger("forex_autopilot.health_monitor")

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
    outbox = EventOutbox()
    date_key = current.strftime("%Y%m%d")
    recorded = []
    for alert in health["alerts"]:
        code = str(alert["code"])
        symbol = str(alert.get("symbol") or "all").upper()
        event = outbox.record(
            event_key=f"health:{code}:{symbol}:{date_key}",
            event_type=code,
            severity=alert["severity"],
            message=alert["message"],
            payload={
                "source": "periodic_health_monitor",
                "alert_code": code,
                "symbol": alert.get("symbol"),
                "health_status": health["status"],
                "assessed_at": health["assessed_at"],
            },
            channel="operator",
            occurred_at=current,
        )
        recorded.append(event["event_id"])
    return {
        "health_status": health["status"],
        "alerts_detected": len(health["alerts"]),
        "events_recorded_or_already_present": len(recorded),
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

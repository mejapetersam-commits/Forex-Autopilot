import { useEffect, useState } from "react";
import { AlertTriangle, BellRing, CheckCircle2, Clock3 } from "lucide-react";
import { getNotificationHealth, type NotificationHealthResponse } from "./api";

function relativeAge(seconds: number | null) {
  if (seconds == null) return "No due item";
  if (seconds < 60) return `${Math.round(seconds)} seconds`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} minutes`;
  return `${(seconds / 3600).toFixed(1)} hours`;
}

export default function NotificationHealth() {
  const [data, setData] = useState<NotificationHealthResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const result = await getNotificationHealth();
        if (active) { setData(result); setError(""); }
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const delivery = data?.delivery;
  return <section className="panel">
    <div className="section-head">
      <div><div className="eyebrow">OPERATIONAL EVENT PIPELINE</div><h2>Alerts & notification outbox</h2>
        <p className="subhead">Tracks durable alert events and delivery queue state. No notification is sent or leased by this dashboard.</p>
      </div>
      <span className="research-tag"><BellRing size={13}/> OBSERVE ONLY</span>
    </div>
    {error && <div className="alert-row"><AlertTriangle size={16}/><span>Outbox summary unavailable: {error}</span></div>}
    <div className="system-evidence-meta"><span>Report updated {data ? new Date(data.updated_at).toLocaleString() : "Awaiting notification-health report"}</span><span>{data ? `${data.active_alert_count} active alert(s)` : "Alert state unknown until report arrives"}</span></div>
    <div className="metrics ops-metrics">
      <article className="metric"><span>PENDING</span><strong>{delivery?.pending ?? "—"}</strong><small>{delivery?.due_pending ?? 0} currently due</small></article>
      <article className="metric"><span>LEASED</span><strong>{delivery?.leased ?? "—"}</strong><small>Claimed by a worker</small></article>
      <article className="metric"><span>DELIVERED</span><strong>{delivery?.delivered ?? "—"}</strong><small>Completed delivery records</small></article>
      <article className="metric"><span>DEAD LETTERS</span><strong>{delivery?.dead ?? "—"}</strong><small>Exceeded retry policy</small></article>
      <article className="metric"><span>ACTIVE ALERTS</span><strong>{data?.active_alert_count ?? "—"}</strong><small>Persisted health conditions</small></article>
    </div>
    <div className="connection-row">
      <div className="connection-icon"><Clock3/></div>
      <div className="connection-copy"><b>Oldest due notification</b><span>{relativeAge(delivery?.oldest_due_age_seconds ?? null)} waiting · {delivery?.total ?? 0} total outbox record(s)</span></div>
      <span className={delivery?.dead ? "signal sell" : "signal buy"}>{delivery?.dead ? "REVIEW REQUIRED" : "NO DEAD LETTERS"}</span>
    </div>
    <h3 className="subsection-title">Active health alerts</h3>
    {(data?.active_alerts ?? []).map(alert => <div className="alert-row" key={alert.alert_key}>
      <AlertTriangle size={16}/><span><b>{alert.event_type}</b> · {alert.message}</span><b>{alert.severity.toUpperCase()}</b>
    </div>)}
    {data && data.active_alerts.length === 0 && <div className="connection-row"><CheckCircle2 size={18}/><span>No persisted health alerts are currently active.</span></div>}
    {!data && !error && <div className="connection-row"><Clock3 size={18}/><span>Waiting for the notification-health report. Alert state is not yet confirmed.</span></div>}
    <h3 className="subsection-title">Recent operational events</h3>
    <div className="table-wrap"><table><thead><tr><th>EVENT</th><th>SEVERITY</th><th>DELIVERY</th><th>ATTEMPTS</th><th>OCCURRED</th></tr></thead><tbody>
      {(data?.recent_events ?? []).map(event => <tr key={event.event_id}>
        <td><b>{event.event_type}</b><small className="reason">{event.message}</small></td>
        <td><span className={`signal ${event.severity === "critical" ? "sell" : event.severity === "warning" ? "neutral" : "buy"}`}>{event.severity.toUpperCase()}</span></td>
        <td>{event.delivery_status}</td><td>{event.attempts}</td><td>{new Date(event.occurred_at).toLocaleString()}</td>
      </tr>)}
      {data && data.recent_events.length === 0 && <tr><td colSpan={5} className="empty">No operational events have been recorded yet.</td></tr>}
      {!data && <tr><td colSpan={5} className="empty">Waiting for notification event history.</td></tr>}
    </tbody></table></div>
    <p className="subhead">Delivery provider configuration and notification dispatch remain separate future work. Pending events are not proof of successful external delivery.</p>
  </section>;
}

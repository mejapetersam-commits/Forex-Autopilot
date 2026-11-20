import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";
import type { ExecutionReconciliationResponse } from "./api";

function stamp(value?: string | null) {
  if (!value) return "No report received";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function Status({ good, children }: { good: boolean; children: ReactNode }) {
  return <span className={`status ${good ? "good" : "bad"}`}><i />{children}</span>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <article className="metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}

export default function ExecutionReconciliation({ data }: { data: ExecutionReconciliationResponse | null }) {
  return <section className="panel">
    <div className="section-head">
      <div><div className="eyebrow">EXECUTION HISTORY</div><h2>Broker fills & reconciliation</h2><p className="subhead">Read-only evidence from durable intent audits and authenticated demo broker history.</p></div>
      <Status good={Boolean(data && data.status !== "review_required")}>{data?.status?.replaceAll("_", " ").toUpperCase() ?? "LOADING"}</Status>
    </div>
    <div className="metrics">
      <Metric label="PARTIAL FILLS" value={String(data?.counts.partial_fill_count ?? "—")} detail="Awaiting additional fill evidence or completion"/>
      <Metric label="RECONCILED INTENTS" value={String(data?.counts.reconciled_count ?? "—")} detail="Broker-confirmed full fill or terminal outcome"/>
      <Metric label="AWAITING HISTORY" value={String(data?.counts.awaiting_history_count ?? "—")} detail="No matching broker deal evidence yet"/>
      <Metric label="UNKNOWN OUTCOMES" value={String(data?.counts.unknown_count ?? "—")} detail="Quarantined; never automatically resent"/>
    </div>
    <div className="metrics">
      <Metric label="BROKER ORDERS" value={String(data?.order_counts.total ?? "—")} detail="Recent broker-reported demo orders"/>
      <Metric label="PENDING ORDERS" value={String(data?.order_counts.pending ?? "—")} detail="Includes placed and partial order states"/>
      <Metric label="TERMINAL ORDERS" value={String(data?.order_counts.terminal ?? "—")} detail="Filled, cancelled, rejected or expired"/>
    </div>
    {Boolean(data?.manual_review_events.length) && <div className="alert-row"><AlertTriangle size={16}/><span>{data?.manual_review_events.length} broker reconciliation exception(s) require manual review. Check broker order/deal history before any separate operator action.</span><b>REVIEW</b></div>}
    <div className="table-wrap"><table><thead><tr><th>INTENT</th><th>SYMBOL / SIDE</th><th>STATUS</th><th>FILLED / REQUESTED</th><th>AVG FILL</th><th>FILL DETAILS</th><th>ORDER / DEALS</th><th>LAST EVIDENCE</th></tr></thead><tbody>
      {data?.intents.map(intent => <tr key={intent.intent_id}>
        <td className="symbol">{intent.intent_id}</td><td>{intent.symbol} / {intent.side.toUpperCase()}</td>
        <td><Status good={intent.result === "full_fill_reconciled"}>{intent.status.replaceAll("_", " ").toUpperCase()}</Status></td>
        <td>{intent.filled_volume_lots.toFixed(3)} / {intent.requested_volume_lots?.toFixed(3) ?? "—"}</td>
        <td>{intent.average_fill_price == null ? "—" : intent.average_fill_price.toFixed(5)}</td>
        <td>{intent.fill_details.length ? intent.fill_details.map(fill => <div key={fill.deal_ticket}>{fill.deal_ticket}: {fill.volume_lots.toFixed(3)} @ {fill.price.toFixed(5)}</div>) : "—"}</td>
        <td>{intent.broker_order_id ?? "—"}{intent.deal_tickets.length ? " · " + intent.deal_tickets.join(", ") : ""}</td>
        <td>{stamp(intent.last_broker_evidence_at)}</td>
      </tr>)}
      {!data?.intents.length && <tr><td colSpan={8} className="empty">No submitted execution intents have been recorded for dashboard review.</td></tr>}
    </tbody></table></div>
    <div className="table-wrap"><table><thead><tr><th>BROKER ORDER</th><th>SYMBOL</th><th>TYPE</th><th>STATE</th><th>EXECUTED / INITIAL</th><th>REMAINING</th><th>PRICE</th><th>SL / TP</th><th>LAST UPDATE</th></tr></thead><tbody>
      {data?.broker_orders.map(order => <tr key={order.order_ticket}>
        <td className="symbol">{order.order_ticket}</td><td>{order.symbol}</td><td>{order.order_type.toUpperCase()}</td>
        <td><Status good={order.state === "filled"}>{order.state.replaceAll("_", " ").toUpperCase()}</Status></td>
        <td>{Math.max(0, order.initial_volume - order.current_volume).toFixed(3)} / {order.initial_volume.toFixed(3)}</td>
        <td>{order.current_volume.toFixed(3)}</td><td>{order.price.toFixed(5)}</td>
        <td>{order.stop_loss > 0 ? order.stop_loss.toFixed(5) : "MISSING"} / {order.take_profit > 0 ? order.take_profit.toFixed(5) : "MISSING"}</td><td>{stamp(order.observed_at)}</td>
      </tr>)}
      {!data?.broker_orders.length && <tr><td colSpan={9} className="empty">No broker order snapshots have been received yet.</td></tr>}
    </tbody></table></div>
    {Boolean(data?.manual_review_events.length) && <div className="table-wrap"><table><thead><tr><th>REVIEW TIME</th><th>INTENT</th><th>SEVERITY</th><th>REASONS</th><th>ORDER</th></tr></thead><tbody>
      {data?.manual_review_events.map(event => <tr key={event.event_id}><td>{stamp(event.occurred_at)}</td><td className="symbol">{event.intent_id ?? "—"}</td><td><Status good={false}>{event.severity.toUpperCase()}</Status></td><td>{event.reasons.join(", ") || event.outcome || "Review required"}</td><td>{event.broker_order_id ?? "—"}</td></tr>)}
    </tbody></table></div>}
    <p className="subhead">Average fill price is volume-weighted across verified entry deals. Order state alone is not treated as proof of execution; missing or uncertain broker evidence never triggers an automatic retry.</p>
  </section>;
}

import { useEffect, useState } from "react";
import { Activity, RefreshCw, ShieldCheck } from "lucide-react";
import { getDemoObservation, type DemoObservationResponse } from "./api";

function stamp(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
export default function DemoObservation() {
  const [data, setData] = useState<DemoObservationResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function refresh() {
    setLoading(true); setError("");
    try { setData(await getDemoObservation()); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to load demo observations"); }
    finally { setLoading(false); }
  }
  useEffect(() => { void refresh(); }, []);
  return <section className="panel demo-observation">
    <div className="section-head">
      <div><div className="eyebrow">FORWARD VALIDATION · BROKER EVIDENCE</div><h2>Demo observation centre</h2><p className="subhead">A factual roll-up of broker-reported demo orders, fills and terminal snapshots. No simulated or inferred trade outcomes.</p></div>
      <button className="lab-secondary" onClick={() => void refresh()} disabled={loading}>{loading ? <RefreshCw size={14} className="spin"/> : <Activity size={14}/>} {loading ? "Refreshing…" : "Refresh evidence"}</button>
    </div>
    {error && <div className="lab-error">{error}</div>}
    {data && <>
      <div className="comparison-summary">
        <div><b>{data.deal_totals.deal_count}</b><span>BROKER DEALS</span></div>
        <div><b>{data.order_totals.order_count}</b><span>HISTORICAL ORDERS</span></div>
        <div><b>{data.deal_totals.strategy_magic_count}</b><span>MAGIC GROUPS</span></div>
      </div>
      <div className="observation-terminal">
        <ShieldCheck size={17}/>
        <div><b>{data.latest_terminal ? "DEMO TERMINAL REPORTING" : "AWAITING TERMINAL SNAPSHOT"}</b><span>{data.latest_terminal ? data.latest_terminal.server + " · " + data.latest_terminal.reported_open_positions + " open positions · observed " + stamp(data.latest_terminal.observed_at) : "No broker execution-state snapshot has been received yet."}</span></div>
        <span className="comparison-status muted">{data.status.replaceAll("_"," ")}</span>
      </div>
      <div className="table-wrap"><table className="comparison-table"><thead><tr><th>MAGIC</th><th>SYMBOL</th><th>DEALS</th><th>ENTRY</th><th>EXIT</th><th>GROSS LOTS</th><th>LAST DEAL</th></tr></thead><tbody>
        {data.groups.map((row) => <tr key={row.magic + row.symbol}><td>{row.magic}</td><td className="symbol">{row.symbol}</td><td>{row.deal_count}</td><td>{row.entry_deals}</td><td>{row.exit_deals}</td><td>{row.gross_deal_volume_lots.toFixed(2)}</td><td>{stamp(row.last_deal_at)}</td></tr>)}
        {!data.groups.length && <tr><td colSpan={7} className="empty">No broker-confirmed demo deals received. This is an empty observation record, not a zero-loss result.</td></tr>}
      </tbody></table></div>
      <div className="observation-limitations"><b>Evidence limitations</b><span>Cash components are now ingested from broker history. See the separate realized P&amp;L panel; legacy deals with missing components remain excluded from its performance metrics.</span><ul>{data.limitations.map(item => <li key={item}>{item}</li>)}</ul></div>
      <div className="lab-footer">READ-ONLY BROKER EVIDENCE · NO STRATEGY ATTRIBUTION CLAIM · EXECUTION DISABLED · UPDATED {stamp(data.updated_at)}</div>
    </>}
  </section>;
}

import { useEffect, useState } from "react";
import { AlertTriangle, Database, RefreshCw } from "lucide-react";
import { getCandleIngestion, type CandleIngestionResponse } from "./api";

function time(value?: string | null) {
  if (!value) return "Not reported";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function age(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "Unknown";
  if (value < 60) return Math.round(value) + " sec ago";
  if (value < 3600) return Math.floor(value / 60) + " min ago";
  if (value < 86400) return (value / 3600).toFixed(1) + " hr ago";
  return (value / 86400).toFixed(1) + " days ago";
}

export default function CandleIngestion() {
  const [data, setData] = useState<CandleIngestionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    setLoading(true);
    try { setData(await getCandleIngestion()); setError(""); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 60000);
    return () => window.clearInterval(timer);
  }, []);

  const series = data?.series ?? [];
  const batches = data?.recent_batches ?? [];
  const candleTotal = series.reduce((sum, item) => sum + item.unique_candles_stored, 0);

  return <section className="panel">
    <div className="section-head">
      <div><div className="eyebrow">MARKET DATA PIPELINE</div><h2>Historical ingestion ledger</h2>
        <p className="subhead">Durable single and bulk MT5 receipts, lifetime upload totals and the stored history range.</p>
        {data && <small className="data-snapshot-time">Ledger response updated {time(data.updated_at)}</small>}
      </div>
      <button className="refresh" onClick={() => void refresh()} disabled={loading}>{loading ? <RefreshCw size={14} className="spin"/> : <Database size={14}/>} Refresh</button>
    </div>
    {error && <div className="alert-row"><AlertTriangle size={16}/><span>Ingestion ledger refresh failed: {error}. {data ? "The last successful receipt snapshot remains visible and may be out of date." : "No ingestion snapshot is currently available."}</span></div>}
    <div className="metrics">
      <article className="metric"><span>TOTAL UPLOAD BATCHES</span><strong>{data ? data.batch_count.toLocaleString() : "—"}</strong><small>{data ? `Showing latest ${data.recent_batch_count.toLocaleString()} receipts` : "Awaiting ledger response"}</small></article>
      <article className="metric"><span>SYMBOL / TIMEFRAME PAIRS</span><strong>{data ? data.series_count : "—"}</strong><small>{data ? "Series with recorded uploads" : "Not yet assessed"}</small></article>
      <article className="metric"><span>CANDLES RECEIVED (LIFETIME)</span><strong>{data ? data.candles_received_total.toLocaleString() : "—"}</strong><small>{data ? "Includes repeat and overlapping uploads" : "Not yet assessed"}</small></article>
      <article className="metric"><span>UNIQUE STORED CANDLES</span><strong>{data ? candleTotal.toLocaleString() : "—"}</strong><small>{data ? "Distinct rows currently in history" : "Not yet assessed"}</small></article>
      <article className="metric"><span>STALE SERIES</span><strong>{data ? data.stale_series_count : "—"}</strong><small>{data ? data.aging_series_count + " aging · threshold " + Math.round(data.stale_after_seconds / 60) + " min" : "Not yet assessed"}</small></article>
      <article className="metric"><span>LAST SUCCESSFUL UPLOAD</span><strong>{data ? age(data.last_successful_upload_age_seconds) : "—"}</strong><small>{data ? time(data.last_successful_upload_at) : "Awaiting ledger response"}</small></article>
    </div>
    {data && data.stale_series_count > 0 && <div className="alert-row"><AlertTriangle size={16}/><span>{data.stale_series_count} candle series have had no successful upload within the {Math.round(data.stale_after_seconds / 60)}-minute threshold. Check the MT5 telemetry sender, terminal connection and ingestion service. This is an upload-inactivity alert, not confirmation that the broker market should currently be open.</span><b>STALE FEED</b></div>}
    {data && data.freshness_status === "no_data" && <div className="alert-row"><AlertTriangle size={16}/><span>No candle upload receipts have been recorded yet. Historical feed freshness cannot be assessed until the first successful batch arrives.</span></div>}
    <h3 className="subsection-title">Per-series ingestion totals</h3>
    <div className="table-wrap"><table><thead><tr><th>SYMBOL</th><th>TIMEFRAME</th><th>BATCHES</th><th>RECEIVED (ALL UPLOADS)</th><th>UNIQUE STORED</th><th>FIRST STORED CANDLE</th><th>LATEST STORED CANDLE</th><th>LAST UPLOAD</th><th>UPLOAD FRESHNESS</th></tr></thead><tbody>
      {series.map(item => <tr key={item.symbol + item.timeframe}><td className="symbol">{item.symbol}</td><td>{item.timeframe}</td><td>{item.batch_count}</td><td>{item.candles_received.toLocaleString()}</td><td>{item.unique_candles_stored.toLocaleString()}</td><td>{time(item.first_stored_candle_at ?? undefined)}</td><td>{time(item.latest_stored_candle_at ?? undefined)}</td><td>{time(item.last_ingested_at)}</td><td><span className={`signal ${item.upload_freshness === "recent" ? "buy" : "neutral"}`}>{item.upload_freshness.replaceAll("_", " ")}{item.upload_age_seconds != null ? " · " + age(item.upload_age_seconds) : ""}</span></td></tr>)}
      {!data && <tr><td colSpan={9} className="empty">{loading ? "Loading ingestion ledger…" : "Ingestion ledger is unavailable. Refresh to retry."}</td></tr>}
      {data && !series.length && <tr><td colSpan={9} className="empty">The ledger responded successfully but contains no series upload receipts yet.</td></tr>}
    </tbody></table></div>
    <h3 className="subsection-title">Latest upload receipts</h3>
    <div className="table-wrap"><table><thead><tr><th>SYMBOL</th><th>TIMEFRAME</th><th>RECEIVED</th><th>FIRST CANDLE</th><th>LAST CANDLE</th><th>INGESTED</th></tr></thead><tbody>
      {batches.slice(0, 20).map(item => <tr key={item.batch_id}><td className="symbol">{item.symbol}</td><td>{item.timeframe}</td><td>{item.received_count.toLocaleString()}</td><td>{time(item.first_candle_at)}</td><td>{time(item.last_candle_at)}</td><td>{time(item.ingested_at)}</td></tr>)}
      {!data && <tr><td colSpan={6} className="empty">{loading ? "Loading upload receipts…" : "Upload receipt history is unavailable."}</td></tr>}
      {data && !batches.length && <tr><td colSpan={6} className="empty">No upload receipts were returned. The first MT5 historical upload has not yet been recorded.</td></tr>}
    </tbody></table></div>
    <p className="subhead">Received totals include repeat uploads of overlapping candles. Unique stored totals count distinct rows currently held in history. Freshness measures time since the last successful upload receipt using a configurable inactivity threshold; it does not infer broker market hours, holidays or session closures, and it does not establish research readiness or authorize execution.</p>
  </section>;
}

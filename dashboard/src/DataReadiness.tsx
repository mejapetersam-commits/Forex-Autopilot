import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Database, RefreshCw } from "lucide-react";
import { getDataReadiness, type DataReadinessResponse } from "./api";

export default function DataReadiness() {
  const [data, setData] = useState<DataReadinessResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    setLoading(true);
    try { setData(await getDataReadiness()); setError(""); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 60000);
    return () => window.clearInterval(timer);
  }, []);

  const items = data?.items ?? [];
  const issueCount = items.reduce((total, item) => total + item.quality.issue_count, 0);
  const gapCount = items.reduce((total, item) => total + item.quality.gap_count, 0);
  const totalCandles = items.reduce((total, item) => total + item.candles_available, 0);

  return <section className="panel">
    <div className="section-head">
      <div><div className="eyebrow">HISTORICAL DATA CONTROL</div><h2>Candle integrity & research readiness</h2>
        <p className="subhead">Coverage and OHLC integrity across approved market/timeframe pairs. Session gaps require broker-calendar review.</p>
      </div>
      <button className="refresh" onClick={() => void refresh()} disabled={loading}>{loading ? <RefreshCw size={14} className="spin"/> : <Database size={14}/>} Refresh</button>
    </div>
    {error && <div className="alert-row"><AlertTriangle size={16}/><span>Data readiness unavailable: {error}</span></div>}
    <div className="metrics">
      <article className="metric"><span>READY SERIES</span><strong>{data ? data.ready_series : "—"}</strong><small>Of {data?.series_checked ?? "—"} monitored pairs</small></article>
      <article className="metric"><span>STORED CANDLES</span><strong>{totalCandles.toLocaleString()}</strong><small>Across monitored history</small></article>
      <article className="metric"><span>INTEGRITY ISSUES</span><strong>{issueCount}</strong><small>Invalid OHLC / timestamps</small></article>
      <article className="metric"><span>TIME GAPS</span><strong>{gapCount}</strong><small>Require session-aware review</small></article>
    </div>
    <div className="connection-row">
      <div className="connection-icon">{data?.status === "ready" ? <CheckCircle2/> : <AlertTriangle/>}</div>
      <div className="connection-copy"><b>{data?.status === "ready" ? "All monitored series meet research history requirements" : "Historical data needs attention"}</b><span>Research minimum: {data?.minimum_candles ?? 500} candles per series · readiness never authorizes execution.</span></div>
      <span className={data?.status === "ready" ? "signal buy" : "signal neutral"}>{data?.status?.replaceAll("_", " ").toUpperCase() ?? "WAITING"}</span>
    </div>
    <div className="table-wrap"><table><thead><tr><th>SYMBOL</th><th>TIMEFRAME</th><th>CANDLES</th><th>VALID OHLC</th><th>COVERAGE</th><th>ISSUES</th><th>GAPS</th><th>READINESS</th></tr></thead><tbody>
      {items.map(item => <tr key={item.symbol + item.timeframe}>
        <td className="symbol">{item.symbol}</td><td>{item.timeframe}</td><td>{item.candles_available.toLocaleString()}</td>
        <td>{item.quality.valid_ohlc_pct.toFixed(1)}%</td><td>{item.coverage_pct.toFixed(1)}%</td>
        <td>{item.quality.issue_count}</td><td>{item.quality.gap_count}</td>
        <td><span className={`signal ${item.ready_for_research ? "buy" : "neutral"}`}>{item.status.replaceAll("_", " ")}</span>
          {item.reasons.length > 0 && <small className="reason">{item.reasons.join(" ")}</small>}</td>
      </tr>)}
      {!items.length && <tr><td colSpan={8} className="empty">Waiting for stored candle history and readiness assessment.</td></tr>}
    </tbody></table></div>
    <p className="subhead">A time gap is not automatically a data-loss incident: weekends, holidays and broker-session closures can be legitimate. This panel is a research-quality check only.</p>
  </section>;
}

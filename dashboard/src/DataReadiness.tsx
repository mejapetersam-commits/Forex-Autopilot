import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Database, RefreshCw, Search } from "lucide-react";
import { getDataReadiness, type DataReadinessResponse } from "./api";

function time(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function DataReadiness() {
  const [data, setData] = useState<DataReadinessResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

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
  const issueCount = items.reduce((total, item) => total + (item.quality?.issue_count ?? 0), 0);
  const gapCount = items.reduce((total, item) => total + (item.quality?.gap_count ?? 0), 0);
  const totalCandles = items.reduce((total, item) => total + item.candles_available, 0);
  const filteredItems = useMemo(() => items.filter(item => {
    const query = search.trim().toLowerCase();
    const matchesSearch = !query || [item.symbol, item.timeframe, item.status, ...item.reasons].some(value => String(value ?? "").toLowerCase().includes(query));
    const matchesStatus = statusFilter === "all" || (statusFilter === "ready" ? item.ready_for_research : !item.ready_for_research);
    return matchesSearch && matchesStatus;
  }), [items, search, statusFilter]);

  return <section className="panel">
    <div className="section-head">
      <div><div className="eyebrow">HISTORICAL DATA CONTROL</div><h2>Candle integrity & research readiness</h2>
        <p className="subhead">Coverage and OHLC integrity across approved market/timeframe pairs. Session gaps require broker-calendar review.</p>
      </div>
      <button className="refresh" onClick={() => void refresh()} disabled={loading}>{loading ? <RefreshCw size={14} className="spin"/> : <Database size={14}/>} Refresh</button>
    </div>
    {error && <div className="alert-row"><AlertTriangle size={16}/><span>Data readiness refresh failed: {error}. {data ? "The last successful snapshot remains displayed and may be out of date." : "No readiness snapshot is currently available."}</span></div>}
    <div className="metrics">
      <article className="metric"><span>READY SERIES</span><strong>{data ? data.ready_series : "—"}</strong><small>{data ? "Of " + data.series_checked + " monitored pairs" : "Awaiting readiness report"}</small></article>
      <article className="metric"><span>STORED CANDLES</span><strong>{data ? totalCandles.toLocaleString() : "—"}</strong><small>{data ? "Across monitored history" : "Not yet assessed"}</small></article>
      <article className="metric"><span>INTEGRITY ISSUES</span><strong>{data ? issueCount : "—"}</strong><small>{data ? "Invalid OHLC / timestamps" : "Not yet assessed"}</small></article>
      <article className="metric"><span>TIME GAPS</span><strong>{data ? gapCount : "—"}</strong><small>{data ? "Require session-aware review" : "Not yet assessed"}</small></article>
    </div>
    <div className="connection-row">
      <div className="connection-icon">{data?.status === "ready" ? <CheckCircle2/> : <AlertTriangle/>}</div>
      <div className="connection-copy"><b>{!data ? "Readiness assessment unavailable" : data.status === "ready" ? "All monitored series meet research history requirements" : "Historical data needs attention"}</b><span>{data ? "Research minimum: " + data.minimum_candles + " candles per series · Assessment updated " + time(data.updated_at) : "Waiting for a successful readiness response. Missing data is not treated as zero or ready."} · Readiness never authorizes execution.</span></div>
      <span className={data?.status === "ready" ? "signal buy" : "signal neutral"}>{data?.status?.replaceAll("_", " ").toUpperCase() ?? "UNKNOWN"}</span>
    </div>
    <div className="data-filter-bar">
      <label className="data-search"><Search size={15}/><input aria-label="Search data series" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search symbol, timeframe or reason"/></label>
      <select aria-label="Filter series readiness" value={statusFilter} onChange={event => setStatusFilter(event.target.value)}><option value="all">All series</option><option value="ready">Research ready</option><option value="attention">Needs attention</option></select>
      <span>{data ? filteredItems.length + " of " + items.length + " series" : "No snapshot"}</span>
    </div>
    <div className="table-wrap"><table><thead><tr><th>SYMBOL</th><th>TIMEFRAME</th><th>CANDLES</th><th>VALID OHLC</th><th>COVERAGE</th><th>ISSUES</th><th>GAPS</th><th>READINESS & EVIDENCE</th></tr></thead><tbody>
      {filteredItems.map(item => <tr key={item.symbol + item.timeframe}>
        <td className="symbol">{item.symbol}</td><td>{item.timeframe}</td><td>{item.candles_available.toLocaleString()}</td>
        <td>{item.quality.valid_ohlc_pct.toFixed(1)}%</td><td>{item.coverage_pct.toFixed(1)}%</td>
        <td>{item.quality.issue_count}</td><td>{item.quality.gap_count}</td>
        <td><span className={`signal ${item.ready_for_research ? "buy" : "neutral"}`}>{item.status.replaceAll("_", " ")}</span>
          <details className="data-quality-detail"><summary>Inspect evidence</summary>
            {item.reasons.length > 0 && <div><b>Readiness reasons</b><ul>{item.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul></div>}
            {item.quality.gaps.length > 0 && <div><b>Reported gaps (up to 5)</b><ul>{item.quality.gaps.slice(0, 5).map((gap, index) => <li key={index}>{time(gap.from)} → {time(gap.to)} · estimated missing intervals: {gap.missing_interval_estimate}</li>)}</ul></div>}
            {item.quality.issues.length > 0 && <div><b>Integrity findings (up to 5)</b><ul>{item.quality.issues.slice(0, 5).map((issue, index) => <li key={index}>Row {issue.index}: {issue.type} — {issue.detail}</li>)}</ul></div>}
            {!item.reasons.length && !item.quality.gaps.length && !item.quality.issues.length && <small>No specific blockers or sample findings were returned for this series.</small>}
          </details>
        </td>
      </tr>)}
      {!data && <tr><td colSpan={8} className="empty">{loading ? "Loading readiness assessment…" : "Readiness data is unavailable. Refresh to retry."}</td></tr>}
      {data && !filteredItems.length && <tr><td colSpan={8} className="empty">{items.length ? "No series match the current filters." : "No monitored series were returned by the readiness assessment."}</td></tr>}
    </tbody></table></div>
    <p className="subhead">A time gap is not automatically a data-loss incident: weekends, holidays and broker-session closures can be legitimate. This panel is a research-quality check only.</p>
  </section>;
}

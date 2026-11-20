import { useState } from "react";
import { ArrowDownUp, BarChart3, RefreshCw } from "lucide-react";
import { getStrategyComparison, type StrategyComparisonResponse } from "./api";

function metric(value: number | null | undefined, suffix = "", digits = 2) {
  return value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits) + suffix;
}
function statusClass(status: string) {
  return status === "completed" ? "good" : status === "insufficient_data" ? "muted" : "bad";
}
export default function StrategyComparison() {
  const [data, setData] = useState<StrategyComparisonResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function load() {
    setLoading(true); setError("");
    try { setData(await getStrategyComparison()); }
    catch (err) { setError(err instanceof Error ? err.message : "Comparison request failed"); }
    finally { setLoading(false); }
  }
  const ranked = [...(data?.items ?? [])].sort((a,b) =>
    (a.research_rank ?? 999) - (b.research_rank ?? 999)
  );
  return <section className="panel strategy-comparison">
    <div className="section-head">
      <div><div className="eyebrow">CROSS-MARKET RESEARCH</div><h2>Strategy comparison matrix</h2><p className="subhead">Compare the same baseline simulation across approved instruments and timeframes.</p></div>
      <button className="lab-secondary" onClick={() => void load()} disabled={loading}>{loading ? <RefreshCw size={14} className="spin"/> : <ArrowDownUp size={14}/>} {loading ? "Comparing…" : "Run comparison"}</button>
    </div>
    {!data && !loading && <div className="lab-empty"><BarChart3 size={24}/><b>No comparison loaded</b><span>Run the comparison to evaluate all available symbol and timeframe combinations.</span></div>}
    {loading && <div className="lab-empty"><RefreshCw size={22} className="spin"/><b>Evaluating research grid</b><span>Running identical historical assumptions across the approved market set.</span></div>}
    {error && <div className="lab-error">{error}</div>}
    {data && <>
      <div className="comparison-summary"><div><b>{data.ranked_count}</b><span>COMPLETED SIMULATIONS</span></div><div><b>{data.items.length}</b><span>MARKET / TIMEFRAME PAIRS</span></div><div><b>0.25%</b><span>RISK PER TRADE ASSUMPTION</span></div></div>
      <div className="table-wrap"><table className="comparison-table"><thead><tr><th>RANK</th><th>MARKET</th><th>TIMEFRAME</th><th>RETURN</th><th>PROFIT FACTOR</th><th>WIN RATE</th><th>MAX DD</th><th>TRADES</th><th>DATA</th></tr></thead><tbody>
        {ranked.map(item => <tr key={item.symbol + item.timeframe}>
          <td className="rank-cell">{item.research_rank ? "#"+item.research_rank : "—"}</td><td className="symbol">{item.symbol}</td><td>{item.timeframe}</td>
          <td className={(item.return_pct ?? 0) >= 0 ? "positive" : "negative"}>{metric(item.return_pct,"%")}</td>
          <td>{metric(item.profit_factor,"",3)}</td><td>{metric(item.win_rate_pct,"%")}</td><td className="negative">{metric(item.max_drawdown_pct,"%")}</td><td>{item.total_trades ?? "—"}</td>
          <td><span className={`comparison-status ${statusClass(item.status)}`}>{item.status.replaceAll("_"," ")}</span>{item.gap_count > 0 && <small className="gap-note">{item.gap_count} gaps</small>}</td>
        </tr>)}
      </tbody></table></div>
      <div className="comparison-warning">{data.warning} Ranking prioritizes profit factor and then return; it is not a strategy approval score. Review trade count, drawdown, candle gaps and walk-forward performance before drawing conclusions.</div>
    </>}
    <div className="lab-footer">FIXED RESEARCH ASSUMPTIONS · HISTORICAL COMPARISON ONLY · EXECUTION DISABLED</div>
  </section>;
}

import { useEffect, useState } from "react";
import { Activity, RefreshCw } from "lucide-react";
import { getTradeAttribution, type TradeAttributionResponse } from "./api";

function amount(value: number | null | undefined, currency: string | null) {
  if (value == null || !Number.isFinite(value)) return "—";
  if (!currency) return value.toFixed(2) + " (currency unknown)";
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
  } catch {
    return value.toFixed(2) + " " + currency;
  }
}
export default function TradeAttribution() {
  const [data, setData] = useState<TradeAttributionResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function refresh() {
    setLoading(true); setError("");
    try { setData(await getTradeAttribution()); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to load broker P&L"); }
    finally { setLoading(false); }
  }
  useEffect(() => { void refresh(); }, []);
  return <section className="panel demo-observation">
    <div className="section-head">
      <div><div className="eyebrow">BROKER-REPORTED RESULTS · DEMO ONLY</div><h2>Realized P&amp;L & trade attribution</h2><p className="subhead">Only fully closed position cycles with complete broker cash components contribute to performance metrics.</p></div>
      <button className="lab-secondary" onClick={() => void refresh()} disabled={loading}>{loading ? <RefreshCw size={14} className="spin"/> : <Activity size={14}/>} {loading ? "Refreshing…" : "Refresh P&L"}</button>
    </div>
    {error && <div className="lab-error">{error}</div>}
    {data && <>
      <div className="comparison-summary">
        <div><b>{amount(data.net_realized_pnl, data.account_currency)}</b><span>NET REALIZED P&amp;L</span></div>
        <div><b>{data.pnl_complete_trade_count}/{data.closed_trade_count}</b><span>COMPLETE CLOSED TRADES</span></div>
        <div><b>{data.win_rate_pct == null ? "—" : data.win_rate_pct.toFixed(1) + "%"}</b><span>WIN RATE</span></div>
        <div><b>{data.profit_factor == null ? "—" : data.profit_factor.toFixed(2)}</b><span>PROFIT FACTOR</span></div>
      </div>
      <div className="comparison-summary">
        <div><b>{amount(data.expectancy_per_trade, data.account_currency)}</b><span>EXPECTANCY / TRADE</span></div>
        <div><b>{amount(data.average_win, data.account_currency)}</b><span>AVERAGE WIN</span></div>
        <div><b>{amount(data.average_loss, data.account_currency)}</b><span>AVERAGE LOSS</span></div>
        <div><b>{amount(data.max_drawdown_cash, data.account_currency)}</b><span>REALIZED DRAWDOWN</span></div>
      </div>
      <div className="observation-terminal"><Activity size={17}/><div><b>{data.coverage.replaceAll("_"," ").toUpperCase()} · {data.account_currency ?? "ACCOUNT CURRENCY UNKNOWN"}</b><span>{data.deal_count} broker deals · coverage {data.history_start ? new Date(data.history_start).toLocaleDateString() : "—"} to {data.history_end ? new Date(data.history_end).toLocaleDateString() : "—"} · {data.open_position_count} still open · {data.unmatched_deal_count} unmatched · {data.overclose_or_ambiguous_count} ambiguous over-closes</span></div><span className="comparison-status muted">{data.status.replaceAll("_"," ")}</span></div>
      <div className="table-wrap"><table className="comparison-table"><thead><tr><th>MAGIC</th><th>SYMBOL</th><th>CLOSED</th><th>COMPLETE</th><th>NET P&amp;L</th><th>WIN RATE</th><th>PROFIT FACTOR</th><th>OPEN</th></tr></thead><tbody>
        {data.groups.map(row => <tr key={row.magic + row.symbol}><td>{row.magic}</td><td className="symbol">{row.symbol}</td><td>{row.closed_trade_count}</td><td>{row.pnl_complete_trade_count}/{row.closed_trade_count}</td><td>{amount(row.net_realized_pnl, data.account_currency)}</td><td>{row.win_rate_pct == null ? "—" : row.win_rate_pct.toFixed(1) + "%"}</td><td>{row.profit_factor == null ? "—" : row.profit_factor.toFixed(2)}</td><td>{row.open_position_count}</td></tr>)}
        {!data.groups.length && <tr><td colSpan={8} className="empty">No broker deal history is available yet.</td></tr>}
      </tbody></table></div>
      <div className="observation-limitations"><b>Data quality & interpretation</b><span>{data.pnl_incomplete_trade_count} closed cycles have missing cash fields; {data.missing_cash_deal_count} deals lack one or more of profit, commission, swap or fee. These are excluded from P&amp;L statistics.</span><ul>{data.limitations.map(item => <li key={item}>{item}</li>)}</ul></div>
      <div className="lab-footer">READ-ONLY · BROKER-DEMO HISTORY · NO AUTOMATIC EXECUTION · UPDATED {new Date(data.updated_at).toLocaleString()}</div>
    </>}
  </section>;
}

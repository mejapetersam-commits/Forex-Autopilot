import { useState } from "react";
import { Activity, FlaskConical, Play, ShieldCheck } from "lucide-react";
import { getCostSensitivity, type CostSensitivityResponse } from "./api";

function metric(value: number | null | undefined, digits = 2) {
  return value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits);
}

export default function CostSensitivity() {
  const [symbol, setSymbol] = useState("EURUSDm");
  const [timeframe, setTimeframe] = useState("H1");
  const [result, setResult] = useState<CostSensitivityResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function run() {
    setLoading(true);
    setError("");
    try {
      setResult(await getCostSensitivity(symbol, timeframe));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Cost sensitivity request failed");
    } finally {
      setLoading(false);
    }
  }

  const baseline = result?.scenarios[0];
  return <section className="panel cost-lab">
    <div className="section-head">
      <div><div className="eyebrow">EXECUTION COST STRESS LAB</div><h2>Would the edge survive higher costs?</h2><p className="subhead">Re-runs the same historical strategy under progressively harsher spread, slippage and commission assumptions.</p></div>
      <span className="research-tag"><FlaskConical size={14}/> RESEARCH ONLY</span>
    </div>
    <div className="lab-toolbar">
      <label>INSTRUMENT<select value={symbol} onChange={event => { setSymbol(event.target.value); setResult(null); }}><option value="EURUSDm">EURUSDm</option><option value="GBPUSDm">GBPUSDm</option></select></label>
      <label>TIMEFRAME<select value={timeframe} onChange={event => { setTimeframe(event.target.value); setResult(null); }}><option value="M15">M15</option><option value="H1">H1</option><option value="H4">H4</option></select></label>
      <button className="lab-run" onClick={() => void run()} disabled={loading}><Play size={14}/>{loading ? "Running stress scenarios…" : "Run cost stress test"}</button>
    </div>
    {error && <div className="lab-error">{error}</div>}
    {!result && !loading && <div className="lab-empty"><Activity size={24}/><b>No stress test loaded</b><span>Choose a market and run four cost scenarios using the same stored historical candles.</span></div>}
    {loading && <div className="lab-empty"><Activity size={24}/><b>Replaying historical data</b><span>Testing base, moderate, high and severe transaction-cost assumptions.</span></div>}
    {result && <>
      <div className="lab-meta"><span>{result.symbol} · {result.timeframe}</span><span>{result.candles_available.toLocaleString()} candles</span><span>Valuation: {result.pip_value_source.replaceAll("_", " ")}</span></div>
      {baseline?.status !== "completed" ? <div className="lab-error">Not enough historical data to produce a completed simulation. Current status: {baseline?.status ?? "unknown"}.</div> : <>
        <div className="cost-baseline">
          <div><span>BASELINE RETURN</span><b className={(baseline?.return_pct ?? 0) >= 0 ? "positive" : "negative"}>{metric(baseline?.return_pct)}%</b></div>
          <div><span>BASELINE PROFIT FACTOR</span><b>{metric(baseline?.profit_factor, 3)}</b></div>
          <div><span>BASELINE TRADES</span><b>{baseline?.total_trades ?? 0}</b></div>
          <div><span>SEVERE-STRESS RETURN</span><b className={(result.scenarios[3]?.return_pct ?? 0) >= 0 ? "positive" : "negative"}>{metric(result.scenarios[3]?.return_pct)}%</b></div>
        </div>
        <div className="table-wrap">
          <table className="comparison-table"><thead><tr><th>SCENARIO</th><th>COST MULTIPLIER</th><th>SPREAD</th><th>SLIPPAGE / SIDE</th><th>COMMISSION / SIDE</th><th>RETURN</th><th>PROFIT FACTOR</th><th>MAX DRAWDOWN</th><th>TRADES</th></tr></thead>
            <tbody>{result.scenarios.map(item => <tr key={item.cost_multiplier}>
              <td className="symbol">{item.label}</td><td>{item.cost_multiplier.toFixed(1)}×</td><td>{metric(item.assumptions.spread_pips, 2)} pips</td><td>{metric(item.assumptions.slippage_pips_per_side, 2)} pips</td><td>{metric(item.assumptions.commission_per_lot_per_side)}</td>
              <td className={(item.return_pct ?? 0) >= 0 ? "positive" : "negative"}>{metric(item.return_pct)}%</td><td>{metric(item.profit_factor, 3)}</td><td>{metric(item.max_drawdown_pct)}%</td><td>{item.total_trades}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <div className="assumption-note"><ShieldCheck size={15}/><span>{result.methodology} A strategy that fails under modest cost increases may be too fragile for further consideration. This is a sensitivity analysis, not proof of future profitability.</span></div>
      </>}
      <div className="lab-footer">READ ONLY · FOUR SCENARIOS · NO ORDERS SUBMITTED · EXECUTION DISABLED</div>
    </>}
  </section>;
}

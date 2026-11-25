import { useState } from "react";
import { Activity, BarChart3, FlaskConical, Play, ShieldCheck } from "lucide-react";
import { getStrategyPerformance, type StrategyPerformanceResponse } from "./api";


function number(value: number | null | undefined, digits = 2) {
  return value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits);
}
function signed(value: number | undefined) {
  return value == null ? "—" : (value > 0 ? "+" : "") + value.toFixed(2) + "%";
}
function EquityChart({ points }: { points: Array<{ time: string | null; equity: number; drawdown_pct: number }> }) {
  if (points.length < 2) return <div className="chart-empty">Run a backtest with sufficient candle history to plot the equity curve.</div>;
  const values = points.map(point => point.equity);
  const min = Math.min(...values), max = Math.max(...values);
  const range = Math.max(max - min, 1);
  const coords = values.map((value, index) => ({
    x: 12 + (index / (values.length - 1)) * 976,
    y: 188 - ((value - min) / range) * 164,
  }));
  const path = coords.map((point, index) => (index ? "L" : "M") + point.x.toFixed(1) + " " + point.y.toFixed(1)).join(" ");
  const area = path + " L 988 196 L 12 196 Z";
  return <div className="equity-chart">
    <svg viewBox="0 0 1000 205" role="img" aria-label="Backtest mark-to-market equity curve">
      <defs><linearGradient id="equityFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#d3f36b" stopOpacity=".22"/><stop offset="100%" stopColor="#d3f36b" stopOpacity="0"/></linearGradient></defs>
      {[32, 82, 132, 182].map(y => <line key={y} x1="12" x2="988" y1={y} y2={y} stroke="#304149" strokeDasharray="4 7"/>)}
      <path d={area} fill="url(#equityFill)"/>
      <path d={path} fill="none" stroke="#d3f36b" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx={coords[coords.length - 1].x} cy={coords[coords.length - 1].y} r="5" fill="#d3f36b"/>
    </svg>
    <div className="chart-scale"><span>LOW {number(min)}</span><span>HIGH {number(max)}</span><span>{points.length} CANDLE MARKS</span></div>
  </div>;
}

export default function StrategyPerformance() {
  const [symbol, setSymbol] = useState("EURUSDm");
  const [timeframe, setTimeframe] = useState("H1");
  const [result, setResult] = useState<StrategyPerformanceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [walkLoading, setWalkLoading] = useState(false);
  const [error, setError] = useState("");

  async function run(includeWalkForward: boolean) {
    if (includeWalkForward) setWalkLoading(true); else setLoading(true);
    setError("");
    try {
      const next = await getStrategyPerformance(symbol, timeframe, includeWalkForward);
      setResult(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Research request failed");
    } finally {
      setLoading(false);
      setWalkLoading(false);
    }
  }

  const backtest = result?.backtest;
  const curve = backtest?.mark_to_market_equity_curve ?? [];
  const wf = result?.walk_forward;

  return <section className="panel strategy-lab">
    <div className="section-head">
      <div><div className="eyebrow">STRATEGY PERFORMANCE LAB</div><h2>Test the edge. Measure the risk.</h2><p className="subhead">Historical simulation and chronological out-of-sample validation. Research only — never an order instruction.</p></div>
      <span className="research-tag"><FlaskConical size={14}/> RESEARCH ONLY</span>
    </div>
    <div className="lab-toolbar">
      <label>INSTRUMENT<select value={symbol} onChange={event => { setSymbol(event.target.value); setResult(null); }}><option value="EURUSDm">EURUSDm</option><option value="GBPUSDm">GBPUSDm</option></select></label>
      <label>TIMEFRAME<select value={timeframe} onChange={event => { setTimeframe(event.target.value); setResult(null); }}><option value="M15">M15</option><option value="H1">H1</option><option value="H4">H4</option></select></label>
      <button className="lab-run" onClick={() => void run(false)} disabled={loading || walkLoading}><Play size={14}/>{loading ? "Running simulation…" : "Run backtest"}</button>
      <button className="lab-secondary" onClick={() => void run(true)} disabled={loading || walkLoading || !result}>{walkLoading ? "Validating…" : "Run walk-forward"}</button>
    </div>
    {error && <div className="lab-error">{error}</div>}
    {!result && !loading && <div className="lab-empty"><BarChart3 size={25}/><b>No simulation loaded</b><span>Select an instrument and timeframe, then run a backtest to populate the performance workspace.</span></div>}
    {loading && <div className="lab-empty"><Activity size={25}/><b>Running historical simulation</b><span>Evaluating completed candles with spread, slippage and commission assumptions.</span></div>}
    {result && <>
      <div className="lab-meta"><span>{result.symbol} · {result.timeframe}</span><span>{result.candles_available.toLocaleString()} candles available</span><span>Data quality: {result.data_quality.status}</span><span>Pip valuation: {result.pip_value_source.replaceAll("_", " ")}</span></div>
      {backtest?.status !== "completed" ? <div className="lab-error">Insufficient historical candles: {backtest?.status ?? "no result"}. Increase available history before evaluating this strategy.</div> : <>
        <div className="metrics lab-metrics">
          <article className="metric"><span>NET RETURN</span><strong className={(backtest.return_pct ?? 0) >= 0 ? "positive" : "negative"}>{signed(backtest.return_pct)}</strong><small>{number(backtest.net_profit) } account currency</small></article>
          <article className="metric"><span>WIN RATE</span><strong>{number(backtest.win_rate_pct)}%</strong><small>{backtest.winning_trades} wins · {backtest.losing_trades} losses</small></article>
          <article className="metric"><span>PROFIT FACTOR</span><strong>{number(backtest.profit_factor, 3)}</strong><small>Gross profit ÷ gross loss</small></article>
          <article className="metric"><span>MAX DRAWDOWN</span><strong className="negative">{number(backtest.mark_to_market_max_drawdown_pct ?? backtest.max_drawdown_pct)}%</strong><small>Intraperiod estimate on candle closes</small></article>
        </div>
        <div className="lab-chart-head"><div><div className="eyebrow">EQUITY DEVELOPMENT</div><h3>Mark-to-market curve</h3></div><span>START {number(backtest.initial_equity)} → END {number(backtest.final_equity)}</span></div>
        <EquityChart points={curve}/>
        <div className="lab-detail-grid">
          <div className="lab-detail"><span>EXPECTANCY / TRADE</span><b>{number(backtest.expectancy_per_trade)}</b></div>
          <div className="lab-detail"><span>TOTAL TRADES</span><b>{backtest.total_trades ?? 0}</b></div>
          <div className="lab-detail"><span>MEDIAN TRADE</span><b>{number(result.analytics?.median_trade_pnl)}</b></div>
          <div className="lab-detail"><span>WORST TRADE</span><b>{number(result.analytics?.worst_trade_pnl)}</b></div>
          <div className="lab-detail"><span>MAX LOSS STREAK</span><b>{result.analytics?.max_consecutive_losses ?? "—"}</b></div>
          <div className="lab-detail"><span>PAYOFF RATIO</span><b>{number(result.analytics?.payoff_ratio, 3)}</b></div>
        </div>
        <div className="assumption-note"><ShieldCheck size={15}/><span>Simulation assumptions: 0.25% risk per trade, 1.0 pip spread, 0.2 pip slippage per side and 3.50 commission per lot per side. OHLC data is not tick-level execution. Historical performance is not a profitability guarantee.</span></div>
      </>}
      {wf && <div className="walk-forward">
        <div className="lab-chart-head"><div><div className="eyebrow">OUT-OF-SAMPLE VALIDATION</div><h3>Walk-forward results</h3></div><span>{wf.status.toUpperCase().replaceAll("_", " ")}</span></div>
        {wf.out_of_sample_summary ? <div className="metrics lab-metrics">
          <article className="metric"><span>VALID FOLDS</span><strong>{wf.out_of_sample_summary.valid_folds}</strong><small>Chronological test windows</small></article>
          <article className="metric"><span>OOS RETURN</span><strong>{signed(wf.out_of_sample_summary.mean_return_pct ?? undefined)}</strong><small>Mean across valid folds</small></article>
          <article className="metric"><span>OOS PROFIT FACTOR</span><strong>{number(wf.out_of_sample_summary.mean_profit_factor, 3)}</strong><small>Mean across valid folds</small></article>
          <article className="metric"><span>WORST OOS DRAWDOWN</span><strong>{number(wf.out_of_sample_summary.worst_drawdown_pct)}%</strong><small>Across validation folds</small></article>
        </div> : <p className="subhead">At least 400 candles are required for walk-forward validation; currently {wf.candles_available ?? result.candles_available} are available.</p>}
        {wf.folds?.map(fold => <div className="fold-row" key={fold.fold}><b>FOLD {fold.fold}</b><span>Training return {signed(fold.training_metrics.return_pct ?? undefined)}</span><span>Out-of-sample {signed(typeof fold.out_of_sample_metrics.return_pct === "number" ? fold.out_of_sample_metrics.return_pct : undefined)}</span><span>{fold.out_of_sample_metrics.total_trades ?? 0} OOS trades</span></div>)}
        {wf.methodology?.warning && <p className="subhead">{wf.methodology.warning}</p>}
      </div>}
    </>}
    <div className="lab-footer">BACKTESTS ARE HISTORICAL RESEARCH · EXECUTION DISABLED · LIVE TRADING UNAVAILABLE</div>
  </section>;
}

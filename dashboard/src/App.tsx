import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, CircleDot, RefreshCw, ShieldCheck, Wifi, WifiOff } from "lucide-react";
import { getOverview, getResearch, type DashboardOverview, type ResearchItem } from "./api";

function money(value?: number, currency = "USD") {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
}
function stamp(value?: string) {
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

export default function App() {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [research, setResearch] = useState<ResearchItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [o, r] = await Promise.all([getOverview(), getResearch()]);
      setOverview(o);
      setResearch(r.items ?? []);
      setLastUpdated(new Date().toISOString());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load dashboard data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const account = overview?.account;
  const alerts = typeof overview?.system_health === "object" ? overview.system_health.alerts ?? [] : [];
  const health = typeof overview?.system_health === "object" ? overview.system_health.status : overview?.system_health;

  return <main className="shell">
    <header className="topbar">
      <div className="brand"><div className="brand-mark"><Activity size={21}/></div><div><b>FOREX AUTOPILOT</b><span>MARKET INTELLIGENCE · DEMO MONITORING</span></div></div>
      <div className="top-actions"><Status good={Boolean(overview?.bridge_connected)}>{overview?.bridge_connected ? "MT5 connected" : "MT5 disconnected"}</Status><button className="refresh" onClick={() => void refresh()} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""}/> Refresh</button></div>
    </header>

    <section className="hero">
      <div><div className="eyebrow">SYSTEM OVERVIEW</div><h1>Trading operations, <em>under control.</em></h1><p>Read-only visibility into broker connectivity, account telemetry and strategy research.</p></div>
      <div className="safety"><ShieldCheck size={19}/><div><b>PROTECTION ACTIVE</b><span>Execution disabled · Live trading unavailable</span></div></div>
    </section>

    {error && <div className="error"><AlertTriangle size={17}/><span>Dashboard data unavailable: {error}. Check that the local API is running.</span></div>}

    <section className="metrics">
      <Metric label="ACCOUNT BALANCE" value={money(account?.balance, account?.account_currency)} detail={account?.fresh ? "Latest broker snapshot" : "No fresh account snapshot"}/>
      <Metric label="EQUITY" value={money(account?.equity, account?.account_currency)} detail={account?.fresh ? "Broker-reported equity" : "Awaiting account telemetry"}/>
      <Metric label="FREE MARGIN" value={money(account?.free_margin, account?.account_currency)} detail="Broker-reported available margin"/>
      <Metric label="SYSTEM HEALTH" value={health ? String(health).toUpperCase() : "—"} detail={alerts.length ? `${alerts.length} active alert(s)` : "No reported alerts"}/>
    </section>

    <section className="panel">
      <div className="section-head"><div><div className="eyebrow">BROKER BRIDGE</div><h2>Connection & market quotes</h2></div><span className="muted">Auto-refresh · 15 seconds</span></div>
      <div className="connection-row"><div className="connection-icon">{overview?.bridge_connected ? <Wifi/> : <WifiOff/>}</div><div className="connection-copy"><b>{overview?.bridge_connected ? "Terminal heartbeat received" : "Waiting for terminal heartbeat"}</b><span>{overview?.heartbeat?.observed_at ? `Last heartbeat: ${stamp(overview.heartbeat.observed_at)}` : "Attach the read-only telemetry EA to begin reporting."}</span></div><Status good={Boolean(overview?.heartbeat?.fresh)}>{overview?.heartbeat?.fresh ? "Fresh" : "Stale / missing"}</Status></div>
      <div className="table-wrap"><table><thead><tr><th>INSTRUMENT</th><th>BID</th><th>ASK</th><th>SPREAD</th><th>TELEMETRY</th></tr></thead><tbody>
        {overview?.quotes.map(q => <tr key={q.symbol}><td className="symbol">{q.symbol}</td><td>{q.bid?.toFixed(5) ?? "—"}</td><td>{q.ask?.toFixed(5) ?? "—"}</td><td>{q.spread?.toFixed(5) ?? (q.ask - q.bid).toFixed(5)}</td><td><Status good={q.fresh}>{q.fresh ? "Fresh" : "Stale"}</Status></td></tr>)}
        {!overview?.quotes.length && <tr><td colSpan={5} className="empty">No quote telemetry received yet.</td></tr>}
      </tbody></table></div>
    </section>

    <section className="panel">
      <div className="section-head"><div><div className="eyebrow">RESEARCH WORKSPACE</div><h2>Strategy candidates</h2><p className="subhead">Signals are informational research outputs, not trade instructions.</p></div><span className="research-tag"><CircleDot size={13}/> RESEARCH ONLY</span></div>
      <div className="table-wrap"><table><thead><tr><th>SYMBOL</th><th>TIMEFRAME</th><th>SIGNAL</th><th>CANDLES</th><th>DATA QUALITY</th><th>GAPS</th></tr></thead><tbody>
        {research.map(item => <tr key={item.symbol + item.timeframe}><td className="symbol">{item.symbol}</td><td>{item.timeframe}</td><td><span className={`signal ${item.signal?.toLowerCase()}`}>{item.signal ?? "—"}</span><small className="reason">{item.reason}</small></td><td>{item.candles}</td><td><Status good={item.data_quality === "healthy"}>{item.data_quality}</Status></td><td>{item.gap_count}</td></tr>)}
        {!research.length && <tr><td colSpan={6} className="empty">Research data will appear when candle history is available.</td></tr>}
      </tbody></table></div>
    </section>

    {alerts.length > 0 && <section className="panel alerts"><div className="section-head"><div><div className="eyebrow">ATTENTION REQUIRED</div><h2>System alerts</h2></div><AlertTriangle/></div>{alerts.map((a, i) => <div className="alert-row" key={i}><AlertTriangle size={16}/><span>{a.message ?? "System alert"}</span><b>{a.severity ?? "NOTICE"}</b></div>)}</section>}

    <footer><span><ShieldCheck size={14}/> READ-ONLY DASHBOARD · EXECUTION DISABLED</span><span>Last refreshed: {stamp(lastUpdated)}</span></footer>
  </main>;
}

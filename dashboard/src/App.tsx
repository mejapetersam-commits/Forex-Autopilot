import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, CircleDot, RefreshCw, ShieldCheck, Wifi, WifiOff } from "lucide-react";
import { getOverview, getResearch, getOperationalEvents, getPortfolio, getDashboardOperations, getRecoveryStatus, getExecutionReconciliation, getReleaseReadiness, type ReleaseReadinessResponse, type DashboardOverview, type ResearchItem, type OperationalEvent, type PortfolioResponse, type DashboardOperations, type RecoveryStatusResponse, type ExecutionReconciliationResponse } from "./api";
import StrategyPerformance from "./StrategyPerformance";
import CostSensitivity from "./CostSensitivity";
import StrategyComparison from "./StrategyComparison";
import DemoObservation from "./DemoObservation";
import TradeAttribution from "./TradeAttribution";
import ExecutionReconciliation from "./ExecutionReconciliation";
import ReleaseReadiness from "./ReleaseReadiness";
import BrokerSpecifications from "./BrokerSpecifications";
import NotificationHealth from "./NotificationHealth";
import DataReadiness from "./DataReadiness";
import CandleIngestion from "./CandleIngestion";

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
  const [events, setEvents] = useState<OperationalEvent[]>([]);
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null);
  const [operations, setOperations] = useState<DashboardOperations | null>(null);
  const [recovery, setRecovery] = useState<RecoveryStatusResponse | null>(null);
  const [executionReconciliation, setExecutionReconciliation] = useState<ExecutionReconciliationResponse | null>(null);
  const [releaseReadiness, setReleaseReadiness] = useState<ReleaseReadinessResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      // Keep each dashboard panel independent: one unavailable endpoint must
      // not hide otherwise healthy broker, research, or operations telemetry.
      const results = await Promise.all([
        getOverview().then(value => ({ ok: true as const, value }), error => ({ ok: false as const, error })),
        getResearch().then(value => ({ ok: true as const, value }), error => ({ ok: false as const, error })),
        getOperationalEvents().then(value => ({ ok: true as const, value }), error => ({ ok: false as const, error })),
        getPortfolio().then(value => ({ ok: true as const, value }), error => ({ ok: false as const, error })),
        getDashboardOperations().then(value => ({ ok: true as const, value }), error => ({ ok: false as const, error })),
        getRecoveryStatus().then(value => ({ ok: true as const, value }), error => ({ ok: false as const, error })),
        getExecutionReconciliation().then(value => ({ ok: true as const, value }), error => ({ ok: false as const, error })),
        getReleaseReadiness().then(value => ({ ok: true as const, value }), error => ({ ok: false as const, error })),
      ]);

      const failures: string[] = [];
      let successes = 0;
      const describeFailure = (section: string, error: unknown) => {
        const detail = error instanceof Error ? error.message : String(error);
        failures.push(`${section}: ${detail}`);
      };

      const [overviewResult, researchResult, eventsResult, portfolioResult, operationsResult, recoveryResult, executionReconciliationResult, releaseReadinessResult] = results;
      if (overviewResult.ok) {
        setOverview(overviewResult.value);
        successes++;
      } else describeFailure("Overview", overviewResult.error);

      if (researchResult.ok) {
        setResearch(researchResult.value.items ?? []);
        successes++;
      } else describeFailure("Research", researchResult.error);

      if (eventsResult.ok) {
        setEvents(eventsResult.value.items ?? []);
        successes++;
      } else describeFailure("Events", eventsResult.error);

      if (portfolioResult.ok) {
        setPortfolio(portfolioResult.value);
        successes++;
      } else describeFailure("Portfolio", portfolioResult.error);

      if (operationsResult.ok) {
        setOperations(operationsResult.value);
        successes++;
      } else describeFailure("Operations", operationsResult.error);

      if (recoveryResult.ok) {
        setRecovery(recoveryResult.value);
        successes++;
      } else describeFailure("Recovery", recoveryResult.error);

      if (executionReconciliationResult.ok) {
        setExecutionReconciliation(executionReconciliationResult.value);
        successes++;
      } else describeFailure("Execution reconciliation", executionReconciliationResult.error);

      if (releaseReadinessResult.ok) {
        setReleaseReadiness(releaseReadinessResult.value);
        successes++;
      } else describeFailure("Release readiness", releaseReadinessResult.error);

      if (successes > 0) setLastUpdated(new Date().toISOString());
      setError(failures.length ? `Some dashboard sections could not refresh — ${failures.join("; ")}` : "");
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

    <nav className="dashboard-nav" aria-label="Dashboard sections">
      <a href="#overview">Overview</a><a href="#connectivity">Connectivity</a><a href="#research">Signals</a><a href="#portfolio">Portfolio</a><a href="#data">Market data</a><a href="#strategy">Performance</a><a href="#operations">Operations</a><a href="#execution">Execution</a><a href="#recovery">Recovery</a><a href="#events">Event log</a>
    </nav>

    {error && <div className="error"><AlertTriangle size={17}/><span>Dashboard refresh warning: {error}. Available sections remain visible; retry refresh after checking the affected service.</span></div>}

    <section id="overview" className="metrics">
      <Metric label="ACCOUNT BALANCE" value={money(account?.balance, account?.account_currency)} detail={account?.fresh ? "Latest broker snapshot" : "No fresh account snapshot"}/>
      <Metric label="EQUITY" value={money(account?.equity, account?.account_currency)} detail={account?.fresh ? "Broker-reported equity" : "Awaiting account telemetry"}/>
      <Metric label="FREE MARGIN" value={money(account?.free_margin, account?.account_currency)} detail="Broker-reported available margin"/>
      <Metric label="SYSTEM HEALTH" value={health ? String(health).toUpperCase() : "—"} detail={alerts.length ? `${alerts.length} active alert(s)` : "No reported alerts"}/>
    </section>

    <section id="connectivity" className="panel">
      <div className="section-head"><div><div className="eyebrow">BROKER BRIDGE</div><h2>Connection & market quotes</h2></div><span className="muted">Auto-refresh · 15 seconds</span></div>
      <div className="connection-row"><div className="connection-icon">{overview?.bridge_connected ? <Wifi/> : <WifiOff/>}</div><div className="connection-copy"><b>{overview?.bridge_connected ? "Terminal heartbeat received" : "Waiting for terminal heartbeat"}</b><span>{overview?.heartbeat?.observed_at ? `Last heartbeat: ${stamp(overview.heartbeat.observed_at)}` : "Attach the read-only telemetry EA to begin reporting."}</span></div><Status good={Boolean(overview?.heartbeat?.fresh)}>{overview?.heartbeat?.fresh ? "Fresh" : "Stale / missing"}</Status></div>
      <div className="table-wrap"><table><thead><tr><th>INSTRUMENT</th><th>BID</th><th>ASK</th><th>SPREAD</th><th>TELEMETRY</th></tr></thead><tbody>
        {overview?.quotes.map(q => <tr key={q.symbol}><td className="symbol">{q.symbol}</td><td>{q.bid?.toFixed(5) ?? "—"}</td><td>{q.ask?.toFixed(5) ?? "—"}</td><td>{q.spread?.toFixed(5) ?? (q.ask - q.bid).toFixed(5)}</td><td><Status good={q.fresh}>{q.fresh ? "Fresh" : "Stale"}</Status></td></tr>)}
        {!overview?.quotes.length && <tr><td colSpan={5} className="empty">No quote telemetry received yet.</td></tr>}
      </tbody></table></div>
    </section>

    <section id="research" className="panel">
      <div className="section-head"><div><div className="eyebrow">RESEARCH WORKSPACE</div><h2>Strategy candidates</h2><p className="subhead">Signals are informational research outputs, not trade instructions.</p></div><span className="research-tag"><CircleDot size={13}/> RESEARCH ONLY</span></div>
      <div className="table-wrap"><table><thead><tr><th>SYMBOL</th><th>TIMEFRAME</th><th>SIGNAL</th><th>CANDLES</th><th>DATA QUALITY</th><th>READINESS</th><th>COVERAGE</th><th>GAPS</th></tr></thead><tbody>
        {research.map(item => <tr key={item.symbol + item.timeframe}><td className="symbol">{item.symbol}</td><td>{item.timeframe}</td><td><span className={`signal ${item.signal?.toLowerCase()}`}>{item.signal ?? "—"}</span><small className="reason">{item.reason}</small></td><td>{item.candles}</td><td><Status good={item.data_quality === "healthy"}>{item.data_quality}</Status></td><td><Status good={item.readiness_status === "ready_for_research"}>{(item.readiness_status ?? "unknown").replaceAll("_", " ")}</Status></td><td>{item.coverage_pct?.toFixed(1) ?? "—"}%</td><td>{item.gap_count}</td></tr>)}
        {!research.length && <tr><td colSpan={8} className="empty">Research data will appear when candle history is available.</td></tr>}
      </tbody></table></div>
    </section>

    {alerts.length > 0 && <section className="panel alerts"><div className="section-head"><div><div className="eyebrow">ATTENTION REQUIRED</div><h2>System alerts</h2></div><AlertTriangle/></div>{alerts.map((a, i) => <div className="alert-row" key={i}><AlertTriangle size={16}/><span>{a.message ?? "System alert"}</span><b>{a.severity ?? "NOTICE"}</b></div>)}</section>}

    <section id="portfolio" className="panel">
      <div className="section-head"><div><div className="eyebrow">PORTFOLIO RISK & EXPOSURE</div><h2>Open-position concentration</h2><p className="subhead">Broker telemetry estimates converted into account currency. Missing or stale inputs are not guessed.</p></div><Status good={portfolio?.status === "healthy"}>{portfolio?.status?.toUpperCase() ?? "LOADING"}</Status></div>
      <div className="metrics">
        <Metric label="OPEN POSITIONS" value={String(portfolio?.open_position_count ?? "—")} detail="Broker-reported positions"/>
        <Metric label="OPEN STOP RISK" value={portfolio?.total_open_stop_risk == null ? "UNKNOWN" : money(portfolio.total_open_stop_risk, portfolio.account_currency ?? "USD")} detail="Only when every position has a valid stop"/>
        <Metric label="ACCOUNT EQUITY" value={portfolio?.account_equity == null ? "—" : money(portfolio.account_equity, portfolio.account_currency ?? "USD")} detail="Latest broker snapshot"/>
        <Metric label="CURRENCY PAIRS" value={String(portfolio?.currencies.length ?? 0)} detail="Currencies with calculated exposure"/>
      </div>
      {Boolean(portfolio?.reasons?.length) && <div className="alert-row"><AlertTriangle size={16}/><span>{portfolio?.reasons?.join(" · ")}</span></div>}
      <div className="table-wrap"><table><thead><tr><th>CURRENCY</th><th>NET EXPOSURE</th><th>GROSS EXPOSURE</th><th>GROSS / EQUITY</th></tr></thead><tbody>
        {portfolio?.currencies.map(item => <tr key={item.currency}><td className="symbol">{item.currency}</td><td>{money(item.net_exposure, portfolio.account_currency ?? "USD")}</td><td>{money(item.gross_exposure, portfolio.account_currency ?? "USD")}</td><td>{item.gross_exposure_pct_equity.toFixed(2)}%</td></tr>)}
        {!portfolio?.currencies.length && <tr><td colSpan={4} className="empty">No current position exposure to report.</td></tr>}
      </tbody></table></div>
      <div className="table-wrap"><table><thead><tr><th>TICKET</th><th>INSTRUMENT</th><th>SIDE</th><th>VOLUME</th><th>NOTIONAL</th><th>STOP RISK</th></tr></thead><tbody>
        {portfolio?.positions.map(position => <tr key={position.ticket}><td>{position.ticket}</td><td className="symbol">{position.symbol}</td><td>{position.side.toUpperCase()}</td><td>{position.volume_lots.toFixed(2)}</td><td>{money(position.notional_account_currency, portfolio.account_currency ?? "USD")}</td><td>{position.estimated_stop_risk == null ? "UNKNOWN" : money(position.estimated_stop_risk, portfolio.account_currency ?? "USD")}</td></tr>)}
        {!portfolio?.positions.length && <tr><td colSpan={6} className="empty">No open positions reported.</td></tr>}
      </tbody></table></div>
      <p className="subhead">Exposure is a notional estimate using the latest quote and broker contract size. Stop risk excludes slippage, commissions and gaps. This panel does not approve or place trades.</p>
    </section>

    <div id="data" className="dashboard-group">
      <div className="group-heading"><div className="eyebrow">DATA & INFRASTRUCTURE</div><h2>Market data quality and broker configuration</h2><p>Inspect incoming history, data integrity, contract metadata and notification delivery.</p></div>
      <details className="dashboard-accordion"><summary>Open market data panels <span>4 panels · ingestion, readiness, broker specs, notifications</span></summary>
      <CandleIngestion />
      <DataReadiness />
      <BrokerSpecifications />
      <NotificationHealth />
      </details>
    </div>

    <div id="strategy" className="dashboard-group">
      <div className="group-heading"><div className="eyebrow">STRATEGY & PERFORMANCE</div><h2>Research results and trade evidence</h2><p>Review strategy results, comparisons, demo observations and trade attribution.</p></div>
      <details className="dashboard-accordion"><summary>Open performance and research panels <span>5 panels · performance, cost stress, comparison, demo, attribution</span></summary>
      <StrategyPerformance />
      <CostSensitivity />
      <StrategyComparison />
      <DemoObservation />
      <TradeAttribution />
      </details>
    </div>

    <div id="operations" className="dashboard-group">
    <div className="group-heading"><div className="eyebrow">OPERATIONS & SAFETY</div><h2>Execution oversight and operational continuity</h2><p>Read-only monitoring of risk gates, position reconciliation, recovery and release conditions.</p></div>
    <details className="dashboard-accordion"><summary>Open operations and safety panels <span>4 panels · execution, recovery, reconciliation, release readiness</span></summary>
    <section id="execution" className="panel">
      <div className="section-head"><div><div className="eyebrow">EXECUTION CONTROL ROOM</div><h2>Position oversight & risk gate</h2><p className="subhead">Live demo-position reconciliation, lifecycle evidence and aggregate risk status. This view is read-only.</p></div><Status good={operations?.read_only === true && operations?.trading_enabled === false}>READ ONLY</Status></div>
      <div className="metrics ops-metrics">
        <Metric label="RECONCILIATION" value={operations?.reconciliation.status.replaceAll("_", " ").toUpperCase() ?? "LOADING"} detail="Managed positions checked against intent ledger"/>
        <Metric label="ORPHANED POSITIONS" value={String(operations?.reconciliation.orphaned_positions.length ?? "—")} detail="Require operator investigation; never auto-closed"/>
        <Metric label="MISSING PROTECTION" value={String(operations?.reconciliation.protection_issues?.length ?? "—")} detail="Broker snapshot lacks SL or TP evidence"/>
        <Metric label="LIFECYCLE EVENTS" value={String(operations?.lifecycle.events.length ?? "—")} detail={operations?.lifecycle.previous_snapshot_available ? "Compared with prior terminal snapshot" : "Waiting for comparable snapshot baseline"}/>
        <Metric label="PORTFOLIO STOP RISK" value={operations?.portfolio_risk_gate.aggregate_stop_risk_pct == null ? "UNKNOWN" : operations.portfolio_risk_gate.aggregate_stop_risk_pct.toFixed(3) + "%"} detail={operations?.portfolio_risk_gate.max_stop_risk_pct != null ? "Ceiling " + operations.portfolio_risk_gate.max_stop_risk_pct.toFixed(2) + "% of equity" : "Aggregate risk ceiling"}/>
      </div>
      <div className={`risk-banner ${operations?.portfolio_risk_gate.approved ? "risk-pass" : "risk-block"}`}>
        <ShieldCheck size={18}/>
        <div><b>{operations?.portfolio_risk_gate.approved ? "AGGREGATE RISK WITHIN LIMIT" : "DISPATCH RISK GATE BLOCKED / UNVERIFIED"}</b>
        <span>{operations?.portfolio_risk_gate.reasons?.length ? operations.portfolio_risk_gate.reasons.join(" · ") : "Fresh, complete portfolio risk is within the configured ceiling."}</span></div>
      </div>
      {Boolean(operations?.reconciliation.protection_issues?.length) && <div className="alert-row"><AlertTriangle size={16}/><span>{operations?.reconciliation.protection_issues?.length ?? 0} managed position(s) lack broker-confirmed stop-loss or take-profit protection. Treat as urgent operator review; this dashboard will not modify positions.</span><b>PROTECTION</b></div>}
      {Boolean(operations?.reconciliation.orphaned_positions.length) && <div className="table-wrap"><table><thead><tr><th>UNMATCHED TICKET</th><th>SYMBOL</th><th>SIDE</th><th>VOLUME</th><th>REVIEW REASON</th></tr></thead><tbody>
        {operations?.reconciliation.orphaned_positions.map(position => <tr key={position.ticket}><td className="symbol">{position.ticket}</td><td>{position.symbol}</td><td>{position.side}</td><td>{position.volume_lots.toFixed(2)}</td><td>{position.reason.replaceAll("_", " ")}</td></tr>)}
      </tbody></table></div>}
      <div className="table-wrap"><table><thead><tr><th>LIFECYCLE EVENT</th><th>POSITION</th><th>DETAIL</th></tr></thead><tbody>
        {operations?.lifecycle.events.map((event, index) => <tr key={String(event.event_type) + index}><td className="symbol">{String(event.event_type).replaceAll("_", " ")}</td><td>{String(event.position_id ?? event.ticket ?? "—")}</td><td>{event.reason ? String(event.reason).replaceAll("_", " ") : event.field ? String(event.field) + ": " + String(event.previous_value ?? "—") + " → " + String(event.current_value ?? "—") : event.reduced_volume_lots != null ? "Reduced by " + String(event.reduced_volume_lots) + " lots" : "Observed in latest broker snapshots"}</td></tr>)}
        {!operations?.lifecycle.events.length && <tr><td colSpan={3} className="empty">No new lifecycle transitions in the latest snapshot comparison.</td></tr>}
      </tbody></table></div>
      <p className="subhead">Unmatched managed positions are flagged for review, never automatically closed. A missing position is not called closed unless broker deal history confirms the full close.</p>
    </section>

    <section id="recovery" className="panel">
      <div className="section-head"><div><div className="eyebrow">RECOVERY & CONTINUITY</div><h2>Backup health & command quarantine</h2><p className="subhead">Verified recovery points and commands held for broker reconciliation. This panel is read-only.</p></div><Status good={Boolean(recovery?.backup_worker.fresh && recovery?.backups.fresh_verified_backup && recovery?.backups.invalid_count === 0)}>{recovery?.backups.status?.replaceAll("_", " ").toUpperCase() ?? "LOADING"}</Status></div>
      <div className="metrics">
        <Metric label="FRESH VERIFIED BACKUP" value={recovery?.backups.fresh_verified_backup ? "YES" : "NO"} detail={recovery?.backups.latest_backup_age_hours == null ? "No verified recovery point" : "Latest is " + recovery.backups.latest_backup_age_hours + " hours old"}/>
        <Metric label="BACKUP WORKER" value={recovery?.backup_worker.fresh ? "HEALTHY" : (recovery?.backup_worker.status?.toUpperCase() ?? "—")} detail={recovery?.backup_worker.age_seconds == null ? "No successful worker heartbeat" : "Last success " + Math.round(recovery.backup_worker.age_seconds / 60) + " min ago"}/>
        <Metric label="QUARANTINED COMMANDS" value={String(recovery?.execution_commands.quarantined_total ?? "—")} detail="Expired or uncertain; never auto-resent"/>
        <Metric label="QUEUED / LEASED" value={String((recovery?.execution_commands.counts.queued ?? 0) + " / " + (recovery?.execution_commands.counts.leased ?? 0))} detail="Transport queue state"/>
      </div>
      {recovery && !recovery.backups.fresh_verified_backup && <div className="alert-row"><AlertTriangle size={16}/><span>No recent verified backup is available. Check the backup worker, storage volume and latest backup logs.</span><b>ATTENTION</b></div>}
      {Boolean(recovery?.backups.invalid_count) && <div className="alert-row"><AlertTriangle size={16}/><span>{recovery?.backups.invalid_count} invalid or future-dated backup snapshot(s) need operator review. They are not automatically deleted.</span><b>REVIEW</b></div>}
      <div className="table-wrap"><table><thead><tr><th>COMMAND</th><th>INTENT</th><th>STATUS</th><th>ATTEMPTS</th><th>TERMINAL</th><th>CREATED</th></tr></thead><tbody>
        {recovery?.execution_commands.quarantined.map(command => <tr key={command.command_id}><td className="symbol">{command.command_id}</td><td>{command.intent_id}</td><td><Status good={false}>{command.status.toUpperCase()}</Status></td><td>{command.attempts}</td><td>{command.terminal_id ?? "—"}</td><td>{stamp(command.created_at)}</td></tr>)}
        {!recovery?.execution_commands.quarantined.length && <tr><td colSpan={6} className="empty">No expired or uncertain execution commands are currently quarantined.</td></tr>}
      </tbody></table></div>
      <p className="subhead">A verified local backup is not an off-device backup. Quarantined commands require broker-history reconciliation and are never automatically redelivered.</p>
    </section>

    <ExecutionReconciliation data={executionReconciliation} />
    <ReleaseReadiness data={releaseReadiness} />

    <section id="events" className="panel">
      <div className="section-head"><div><div className="eyebrow">OPERATIONS JOURNAL</div><h2>Recent system events</h2><p className="subhead">Durable event history and notification queue status. No external messages are sent by this view.</p></div><span className="research-tag">{events.length} RECENT</span></div>
      <div className="table-wrap"><table><thead><tr><th>TIME</th><th>SEVERITY</th><th>EVENT</th><th>DETAIL</th><th>DELIVERY</th><th>ATTEMPTS</th></tr></thead><tbody>
        {events.map(event => <tr key={event.event_id}><td>{stamp(event.occurred_at)}</td><td><Status good={event.severity === "info"}>{event.severity.toUpperCase()}</Status></td><td className="symbol">{event.event_type}</td><td>{event.message}</td><td>{event.delivery_status}</td><td>{event.attempts}</td></tr>)}
        {!events.length && <tr><td colSpan={6} className="empty">No operational events have been recorded yet.</td></tr>}
      </tbody></table></div>
    </section>
    </details>

    </div>

    <footer><span><ShieldCheck size={14}/> READ-ONLY DASHBOARD · EXECUTION DISABLED</span><span>Last refreshed: {stamp(lastUpdated)}</span></footer>
  </main>;
}

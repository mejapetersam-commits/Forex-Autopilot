import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, Bell, CircleDot, RefreshCw, ShieldCheck, Wifi, WifiOff } from "lucide-react";
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
  const [page, setPage] = useState<"overview" | "market" | "portfolio" | "strategies" | "risk" | "system">("overview");
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [eventSearch, setEventSearch] = useState("");
  const [eventSeverity, setEventSeverity] = useState("all");
  const [quoteSearch, setQuoteSearch] = useState("");
  const [quoteFreshness, setQuoteFreshness] = useState("all");
  const [researchSearch, setResearchSearch] = useState("");
  const [researchTimeframe, setResearchTimeframe] = useState("all");
  const [researchReadiness, setResearchReadiness] = useState("all");
  const [researchSignal, setResearchSignal] = useState("all");
  const [researchSort, setResearchSort] = useState("symbol");
  const [positionSearch, setPositionSearch] = useState("");
  const [positionSide, setPositionSide] = useState("all");
  const [positionSort, setPositionSort] = useState("symbol");
  const [currencySearch, setCurrencySearch] = useState("");
  const [currencySort, setCurrencySort] = useState("gross");
  const notificationCloseRef = useRef<HTMLButtonElement | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    try {
      return window.localStorage.getItem("forex-autopilot-theme") === "dark" ? "dark" : "light";
    } catch {
      return "light";
    }
  });

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

  useEffect(() => {
    if (!notificationsOpen) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    notificationCloseRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNotificationsOpen(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus();
    };
  }, [notificationsOpen]);

  useEffect(() => {
    try {
      window.localStorage.setItem("forex-autopilot-theme", theme);
    } catch {
      // Theme preference is optional; the dashboard remains usable if storage is unavailable.
    }
  }, [theme]);

  const account = overview?.account;
  const alerts = typeof overview?.system_health === "object" ? overview.system_health.alerts ?? [] : [];
  const health = typeof overview?.system_health === "object" ? overview.system_health.status : overview?.system_health;
  const filteredQuotes = (overview?.quotes ?? []).filter(quote => {
    const matchesSearch = quote.symbol.toLowerCase().includes(quoteSearch.trim().toLowerCase());
    const matchesFreshness = quoteFreshness === "all" || (quoteFreshness === "fresh" ? quote.fresh : !quote.fresh);
    return matchesSearch && matchesFreshness;
  });
  const filteredResearch = research.filter(item => {
    const query = researchSearch.trim().toLowerCase();
    const matchesSearch = !query || [item.symbol, item.timeframe, item.signal, item.reason, item.data_quality, item.readiness_status].some(value => String(value ?? "").toLowerCase().includes(query));
    const matchesTimeframe = researchTimeframe === "all" || item.timeframe === researchTimeframe;
    const matchesReadiness = researchReadiness === "all" || (researchReadiness === "ready" ? item.readiness_status === "ready_for_research" : item.readiness_status !== "ready_for_research");
    const matchesSignal = researchSignal === "all" || item.signal.toLowerCase() === researchSignal;
    return matchesSearch && matchesTimeframe && matchesReadiness && matchesSignal;
  });
  const sortedResearch = [...filteredResearch].sort((a, b) => {
    if (researchSort === "coverage") return (b.coverage_pct ?? -1) - (a.coverage_pct ?? -1);
    if (researchSort === "candles") return b.candles - a.candles;
    if (researchSort === "gaps") return a.gap_count - b.gap_count;
    return a.symbol.localeCompare(b.symbol) || a.timeframe.localeCompare(b.timeframe);
  });
  const filteredPositions = (portfolio?.positions ?? []).filter(position => {
    const query = positionSearch.trim().toLowerCase();
    const matchesSearch = !query || [position.ticket, position.symbol, position.side].some(value => String(value ?? "").toLowerCase().includes(query));
    const matchesSide = positionSide === "all" || position.side.toLowerCase() === positionSide;
    return matchesSearch && matchesSide;
  });
  const sortedPositions = [...filteredPositions].sort((a, b) => {
    if (positionSort === "volume") return b.volume_lots - a.volume_lots;
    if (positionSort === "notional") return b.notional_account_currency - a.notional_account_currency;
    if (positionSort === "risk") return (b.estimated_stop_risk ?? -1) - (a.estimated_stop_risk ?? -1);
    return a.symbol.localeCompare(b.symbol) || a.ticket.localeCompare(b.ticket);
  });
  const filteredCurrencies = (portfolio?.currencies ?? []).filter(item => item.currency.toLowerCase().includes(currencySearch.trim().toLowerCase()));
  const sortedCurrencies = [...filteredCurrencies].sort((a, b) => {
    if (currencySort === "net") return Math.abs(b.net_exposure) - Math.abs(a.net_exposure);
    if (currencySort === "ratio") return b.gross_exposure_pct_equity - a.gross_exposure_pct_equity;
    if (currencySort === "currency") return a.currency.localeCompare(b.currency);
    return b.gross_exposure - a.gross_exposure;
  });
  const filteredEvents = events.filter(event => {
    const query = eventSearch.trim().toLowerCase();
    const matchesQuery = !query || [event.event_type, event.message, event.delivery_status, event.severity].some(value => String(value ?? "").toLowerCase().includes(query));
    const matchesSeverity = eventSeverity === "all" || event.severity.toLowerCase() === eventSeverity;
    return matchesQuery && matchesSeverity;
  });

  return <main className={`shell page-${page} theme-${theme}`}>
    <header className="topbar">
      <div className="brand"><div className="brand-mark"><Activity size={21}/></div><div><b>FOREX AUTOPILOT</b><span>MARKET INTELLIGENCE · DEMO MONITORING</span></div></div>
      <div className="top-actions"><Status good={Boolean(overview?.bridge_connected)}>{overview?.bridge_connected ? "MT5 connected" : "MT5 disconnected"}</Status><button className="notification-trigger" type="button" aria-label={`Open notifications, ${alerts.length} active alerts`} aria-expanded={notificationsOpen} onClick={() => setNotificationsOpen(value => !value)}><Bell size={16}/><span>Alerts</span>{alerts.length > 0 && <i>{alerts.length}</i>}</button><button className="refresh" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>{theme === "light" ? "Dark mode" : "Light mode"}</button><button className="refresh" onClick={() => void refresh()} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""}/> Refresh</button></div>
    </header>

    <section className="hero">
      <div><div className="eyebrow">SYSTEM OVERVIEW</div><h1>Trading operations, <em>under control.</em></h1><p>Read-only visibility into broker connectivity, account telemetry and strategy research.</p></div>
      <div className="safety"><ShieldCheck size={19}/><div><b>PROTECTION ACTIVE</b><span>Execution disabled · Live trading unavailable</span></div></div>
    </section>

    <nav className="dashboard-nav" aria-label="Main navigation">
      {([["overview","Overview"],["market","Market Watch"],["portfolio","Portfolio"],["strategies","Strategies"],["risk","Risk & Safety"],["system","System Centre"]] as const).map(([key,label]) => <button key={key} type="button" className={page === key ? "active" : ""} aria-current={page === key ? "page" : undefined} onClick={() => setPage(key)}>{label}{key === "system" && alerts.length > 0 && <span className="nav-count" aria-label={alerts.length + " active alerts"}>{alerts.length}</span>}</button>)}
    </nav>
    <div className="page-intro"><div className="eyebrow">YOUR TRADING WORKSPACE</div><h2>{({overview:"Welcome to your overview",market:"Market Watch",portfolio:"Portfolio",strategies:"Strategies & research",risk:"Risk & safety",system:"System centre"} as const)[page]}</h2><p>{({overview:"Your essential account and system snapshot, all in one place.",market:"Quotes, candidate signals and historical market data.",portfolio:"Exposure, positions and portfolio risk information.",strategies:"Research, backtesting and strategy comparisons.",risk:"Operational safeguards, recovery and release readiness.",system:"Broker connectivity, specifications, notifications and event history."} as const)[page]}</p></div>

    {error && <div className="error"><AlertTriangle size={17}/><span>Dashboard refresh warning: {error}. Available sections remain visible; retry refresh after checking the affected service.</span></div>}

    {page === "overview" && <section id="overview" className="metrics">
      <Metric label="ACCOUNT BALANCE" value={money(account?.balance, account?.account_currency)} detail={account?.fresh ? "Latest broker snapshot" : "No fresh account snapshot"}/>
      <Metric label="EQUITY" value={money(account?.equity, account?.account_currency)} detail={account?.fresh ? "Broker-reported equity" : "Awaiting account telemetry"}/>
      <Metric label="FREE MARGIN" value={money(account?.free_margin, account?.account_currency)} detail="Broker-reported available margin"/>
      <Metric label="SYSTEM HEALTH" value={health ? String(health).toUpperCase() : "—"} detail={alerts.length ? `${alerts.length} active alert(s)` : "No reported alerts"}/>
    </section>}

    {page === "overview" && <section className="overview-grid" aria-label="Live account and system snapshot">
      <article className="panel overview-card">
        <div className="section-head"><div><div className="eyebrow">ACCOUNT & CONNECTION</div><h2>Broker snapshot</h2></div><Status good={Boolean(overview?.heartbeat?.fresh && account?.fresh)}>{overview?.heartbeat?.fresh && account?.fresh ? "TELEMETRY FRESH" : "TELEMETRY UNVERIFIED"}</Status></div>
        <div className="snapshot-list">
          <div><span>MT5 bridge</span><b>{overview?.bridge_connected ? "Connected" : "Disconnected"}</b></div>
          <div><span>Terminal heartbeat</span><b>{overview?.heartbeat?.observed_at ? stamp(overview.heartbeat.observed_at) : "Not received"}</b></div>
          <div><span>Account snapshot</span><b>{account?.observed_at ? stamp(account.observed_at) : "Not received"}</b></div>
          <div><span>Account currency</span><b>{account?.account_currency ?? "Not reported"}</b></div>
        </div>
        <p className="overview-note">A connected bridge does not by itself confirm fresh account data. Stale or missing telemetry remains unverified.</p>
      </article>
      <article className="panel overview-card">
        <div className="section-head"><div><div className="eyebrow">MARKET PULSE</div><h2>Latest quotes</h2></div><button className="text-action" type="button" onClick={() => setPage("market")}>Open Market Watch →</button></div>
        <div className="quote-list">
          {overview?.quotes.slice(0, 4).map(quote => <div className="quote-item" key={quote.symbol}>
            <div><b>{quote.symbol}</b><span>{quote.fresh ? "Fresh quote" : "Stale quote"}</span></div>
            <div className="quote-values"><b>{Number.isFinite(quote.bid) ? quote.bid.toFixed(5) : "—"}</b><span>Bid</span></div>
            <div className="quote-values"><b>{Number.isFinite(quote.ask) ? quote.ask.toFixed(5) : "—"}</b><span>Ask</span></div>
            <Status good={quote.fresh}>{quote.fresh ? "Fresh" : "Stale"}</Status>
          </div>)}
          {!overview?.quotes.length && <p className="empty">No market quotes have been received yet.</p>}
        </div>
      </article>
      <article className="panel overview-card overview-activity">
        <div className="section-head"><div><div className="eyebrow">OPERATIONS JOURNAL</div><h2>Recent activity</h2></div><button className="text-action" type="button" onClick={() => setPage("system")}>View event log →</button></div>
        {events.slice(0, 3).map(event => <div className="activity-item" key={event.event_id}>
          <span className={`activity-dot ${event.severity}`} />
          <div><b>{event.event_type.replaceAll("_", " ")}</b><span>{event.message}</span><small>{stamp(event.occurred_at)} · {event.delivery_status}</small></div>
          <span className="activity-severity">{event.severity}</span>
        </div>)}
        {!events.length && <p className="empty">No operational events have been recorded yet.</p>}
      </article>
      <article className="panel overview-card overview-safety">
        <div className="section-head"><div><div className="eyebrow">SAFETY POSTURE</div><h2>Execution remains disabled</h2></div><ShieldCheck size={22}/></div>
        <p>This workspace is monitoring-only. It does not submit, modify, or close trades.</p>
        <div className="safety-facts"><span>Trading enabled</span><b>No</b><span>Dashboard mode</span><b>Read only</b><span>Active alerts</span><b>{alerts.length}</b></div>
        <button className="text-action" type="button" onClick={() => setPage("risk")}>Review risk & safeguards →</button>
      </article>
    </section>}

    {page === "market" && <section id="connectivity" className="panel">
      <div className="section-head"><div><div className="eyebrow">BROKER BRIDGE</div><h2>Connection & market quotes</h2></div><span className="muted">Auto-refresh · 15 seconds</span></div>
      <div className="connection-row"><div className="connection-icon">{overview?.bridge_connected ? <Wifi/> : <WifiOff/>}</div><div className="connection-copy"><b>{overview?.bridge_connected ? "Terminal heartbeat received" : "Waiting for terminal heartbeat"}</b><span>{overview?.heartbeat?.observed_at ? `Last heartbeat: ${stamp(overview.heartbeat.observed_at)}` : "Attach the read-only telemetry EA to begin reporting."}</span></div><Status good={Boolean(overview?.heartbeat?.fresh)}>{overview?.heartbeat?.fresh ? "Fresh" : "Stale / missing"}</Status></div>
      <div className="market-tools" aria-label="Market quote filters">
        <label className="market-search"><span>SEARCH INSTRUMENTS</span><input type="search" value={quoteSearch} onChange={event => setQuoteSearch(event.target.value)} placeholder="Find a symbol, e.g. EURUSD"/></label>
        <label className="market-filter"><span>TELEMETRY</span><select value={quoteFreshness} onChange={event => setQuoteFreshness(event.target.value)}><option value="all">All quotes</option><option value="fresh">Fresh only</option><option value="stale">Stale only</option></select></label>
        <span className="market-count" aria-live="polite">{filteredQuotes.length} of {overview?.quotes.length ?? 0} instruments</span>
        {(quoteSearch || quoteFreshness !== "all") && <button className="event-reset" type="button" onClick={() => {setQuoteSearch("");setQuoteFreshness("all");}}>Clear</button>}
      </div>
      <div className="table-wrap"><table><thead><tr><th>INSTRUMENT</th><th>BID</th><th>ASK</th><th>SPREAD</th><th>TELEMETRY</th></tr></thead><tbody>
        {filteredQuotes.map(q => <tr key={q.symbol}><td className="symbol">{q.symbol}</td><td>{q.bid?.toFixed(5) ?? "—"}</td><td>{q.ask?.toFixed(5) ?? "—"}</td><td>{q.spread?.toFixed(5) ?? (q.ask - q.bid).toFixed(5)}</td><td><Status good={q.fresh}>{q.fresh ? "Fresh" : "Stale"}</Status></td></tr>)}
        {!overview?.quotes.length && <tr><td colSpan={5} className="empty">No quote telemetry received yet.</td></tr>}
        {Boolean(overview?.quotes.length) && !filteredQuotes.length && <tr><td colSpan={5} className="empty">No instruments match these filters. Clear the search or freshness filter.</td></tr>}
      </tbody></table></div>
    </section>}

    {page === "market" && <section id="research" className="panel">
      <div className="section-head"><div><div className="eyebrow">RESEARCH WORKSPACE</div><h2>Strategy candidates</h2><p className="subhead">Signals are informational research outputs, not trade instructions.</p></div><span className="research-tag"><CircleDot size={13}/> RESEARCH ONLY</span></div>
      <div className="market-tools research-tools" aria-label="Research candidate filters">
        <label className="market-search"><span>SEARCH RESEARCH</span><input type="search" value={researchSearch} onChange={event => setResearchSearch(event.target.value)} placeholder="Symbol, signal, reason or quality"/></label>
        <label className="market-filter"><span>TIMEFRAME</span><select value={researchTimeframe} onChange={event => setResearchTimeframe(event.target.value)}><option value="all">All timeframes</option>{Array.from(new Set(research.map(item => item.timeframe))).sort().map(timeframe => <option key={timeframe} value={timeframe}>{timeframe}</option>)}</select></label>
        <label className="market-filter"><span>READINESS</span><select value={researchReadiness} onChange={event => setResearchReadiness(event.target.value)}><option value="all">All readiness</option><option value="ready">Ready for research</option><option value="not-ready">Not ready / unknown</option></select></label>
        <label className="market-filter"><span>SIGNAL</span><select value={researchSignal} onChange={event => setResearchSignal(event.target.value)}><option value="all">All signals</option>{Array.from(new Set(research.map(item => item.signal.toLowerCase()))).sort().map(signal => <option key={signal} value={signal}>{signal.toUpperCase()}</option>)}</select></label>
        <label className="market-filter"><span>SORT BY</span><select value={researchSort} onChange={event => setResearchSort(event.target.value)}><option value="symbol">Instrument</option><option value="coverage">Coverage · highest</option><option value="candles">Candles · most</option><option value="gaps">Gaps · fewest</option></select></label>
        <span className="market-count" aria-live="polite">{filteredResearch.length} of {research.length} candidates</span>
        {(researchSearch || researchTimeframe !== "all" || researchReadiness !== "all" || researchSignal !== "all") && <button className="event-reset" type="button" onClick={() => {setResearchSearch("");setResearchTimeframe("all");setResearchReadiness("all");setResearchSignal("all");}}>Clear</button>}
      </div>
      <div className="table-wrap"><table><thead><tr><th>SYMBOL</th><th>TIMEFRAME</th><th>SIGNAL</th><th>CANDLES</th><th>DATA QUALITY</th><th>READINESS</th><th>COVERAGE</th><th>GAPS</th></tr></thead><tbody>
        {sortedResearch.map(item => <tr key={item.symbol + item.timeframe}><td className="symbol">{item.symbol}</td><td>{item.timeframe}</td><td><span className={`signal ${item.signal?.toLowerCase()}`}>{item.signal ?? "—"}</span><small className="reason">{item.reason}</small></td><td>{item.candles}</td><td><Status good={item.data_quality === "healthy"}>{item.data_quality}</Status></td><td><Status good={item.readiness_status === "ready_for_research"}>{(item.readiness_status ?? "unknown").replaceAll("_", " ")}</Status></td><td>{item.coverage_pct?.toFixed(1) ?? "—"}%</td><td>{item.gap_count}</td></tr>)}
        {!research.length && <tr><td colSpan={8} className="empty">Research data will appear when candle history is available.</td></tr>}
        {Boolean(research.length) && !filteredResearch.length && <tr><td colSpan={8} className="empty">No research candidates match these filters. Clear the search or adjust the selections.</td></tr>}
      </tbody></table></div>
    </section>}

    {alerts.length > 0 && <section className="panel alerts"><div className="section-head"><div><div className="eyebrow">ATTENTION REQUIRED</div><h2>System alerts</h2></div><AlertTriangle/></div>{alerts.map((a, i) => <div className="alert-row" key={i}><AlertTriangle size={16}/><span>{a.message ?? "System alert"}</span><b>{a.severity ?? "NOTICE"}</b></div>)}</section>}

    {page === "portfolio" && <section id="portfolio" className="panel">
      <div className="section-head"><div><div className="eyebrow">PORTFOLIO RISK & EXPOSURE</div><h2>Open-position concentration</h2><p className="subhead">Broker telemetry estimates converted into account currency. Missing or stale inputs are not guessed.</p></div><Status good={portfolio?.status === "healthy"}>{portfolio?.status?.toUpperCase() ?? "LOADING"}</Status></div>
      <div className="metrics">
        <Metric label="OPEN POSITIONS" value={String(portfolio?.open_position_count ?? "—")} detail="Broker-reported positions"/>
        <Metric label="OPEN STOP RISK" value={portfolio?.total_open_stop_risk == null ? "UNKNOWN" : money(portfolio.total_open_stop_risk, portfolio.account_currency ?? "USD")} detail="Only when every position has a valid stop"/>
        <Metric label="ACCOUNT EQUITY" value={portfolio?.account_equity == null ? "—" : money(portfolio.account_equity, portfolio.account_currency ?? "USD")} detail="Latest broker snapshot"/>
        <Metric label="CURRENCY PAIRS" value={String(portfolio?.currencies.length ?? 0)} detail="Currencies with calculated exposure"/>
      </div>
      {Boolean(portfolio?.reasons?.length) && <div className="alert-row"><AlertTriangle size={16}/><span>{portfolio?.reasons?.join(" · ")}</span></div>}
      <div className="portfolio-block-head"><div><h3>Currency exposure</h3><p>Ranked using the broker-reported portfolio snapshot.</p></div><span className="market-count">{filteredCurrencies.length} of {portfolio?.currencies.length ?? 0} currencies</span></div>
      <div className="market-tools" aria-label="Currency exposure filters">
        <label className="market-search"><span>FIND CURRENCY</span><input type="search" value={currencySearch} onChange={event => setCurrencySearch(event.target.value)} placeholder="Search currency, e.g. USD"/></label>
        <label className="market-filter"><span>SORT EXPOSURE</span><select value={currencySort} onChange={event => setCurrencySort(event.target.value)}><option value="gross">Highest gross</option><option value="net">Largest net</option><option value="ratio">Gross / equity</option><option value="currency">Currency A–Z</option></select></label>
        {(currencySearch || currencySort !== "gross") && <button className="event-reset" type="button" onClick={() => {setCurrencySearch("");setCurrencySort("gross");}}>Clear</button>}
      </div>
      <div className="table-wrap"><table><thead><tr><th>CURRENCY</th><th>NET EXPOSURE</th><th>GROSS EXPOSURE</th><th>GROSS / EQUITY</th></tr></thead><tbody>
        {sortedCurrencies.map(item => <tr key={item.currency}><td className="symbol">{item.currency}</td><td>{money(item.net_exposure, portfolio?.account_currency ?? "USD")}</td><td>{money(item.gross_exposure, portfolio?.account_currency ?? "USD")}</td><td>{Number.isFinite(item.gross_exposure_pct_equity) ? item.gross_exposure_pct_equity.toFixed(2) + "%" : "—"}</td></tr>)}
        {!portfolio?.currencies.length && <tr><td colSpan={4} className="empty">No current position exposure to report.</td></tr>}
        {Boolean(portfolio?.currencies.length) && !sortedCurrencies.length && <tr><td colSpan={4} className="empty">No currencies match this search.</td></tr>}
      </tbody></table></div>
      <div className="portfolio-block-head"><div><h3>Open positions</h3><p>Filter and sort the positions received from the broker.</p></div><span className="market-count">{filteredPositions.length} of {portfolio?.positions.length ?? 0} positions</span></div>
      <div className="market-tools" aria-label="Open position filters">
        <label className="market-search"><span>SEARCH POSITIONS</span><input type="search" value={positionSearch} onChange={event => setPositionSearch(event.target.value)} placeholder="Find symbol, ticket or side"/></label>
        <label className="market-filter"><span>SIDE</span><select value={positionSide} onChange={event => setPositionSide(event.target.value)}><option value="all">All sides</option><option value="buy">Buy only</option><option value="sell">Sell only</option></select></label>
        <label className="market-filter"><span>SORT BY</span><select value={positionSort} onChange={event => setPositionSort(event.target.value)}><option value="symbol">Instrument A–Z</option><option value="volume">Largest volume</option><option value="notional">Largest notional</option><option value="risk">Highest known stop risk</option></select></label>
        {(positionSearch || positionSide !== "all" || positionSort !== "symbol") && <button className="event-reset" type="button" onClick={() => {setPositionSearch("");setPositionSide("all");setPositionSort("symbol");}}>Clear</button>}
      </div>
      <div className="table-wrap"><table><thead><tr><th>TICKET</th><th>INSTRUMENT</th><th>SIDE</th><th>VOLUME</th><th>NOTIONAL</th><th>STOP RISK</th></tr></thead><tbody>
        {sortedPositions.map(position => <tr key={position.ticket}><td>{position.ticket}</td><td className="symbol">{position.symbol}</td><td>{position.side.toUpperCase()}</td><td>{position.volume_lots.toFixed(2)}</td><td>{money(position.notional_account_currency, portfolio?.account_currency ?? "USD")}</td><td>{position.estimated_stop_risk == null ? "UNKNOWN" : money(position.estimated_stop_risk, portfolio?.account_currency ?? "USD")}</td></tr>)}
        {!portfolio?.positions.length && <tr><td colSpan={6} className="empty">No open positions reported.</td></tr>}
        {Boolean(portfolio?.positions.length) && !sortedPositions.length && <tr><td colSpan={6} className="empty">No positions match these filters.</td></tr>}
      </tbody></table></div>
      <div className="portfolio-footnote"><span>Portfolio snapshot updated</span><b>{portfolio?.updated_at ? stamp(portfolio.updated_at) : "Not yet reported"}</b></div>
      <p className="subhead">Exposure is a notional estimate using the latest quote and broker contract size. Stop risk excludes slippage, commissions and gaps. Unknown stop risk remains unknown; this panel does not approve or place trades.</p>
    </section>}

    {page === "market" && <div id="data" className="dashboard-group">
      <div className="group-heading"><div className="eyebrow">DATA & INFRASTRUCTURE</div><h2>Market data quality and broker configuration</h2><p>Inspect incoming history, data integrity, contract metadata and notification delivery.</p></div>
      <details className="dashboard-accordion"><summary>Open market data panels <span>4 panels · ingestion, readiness, broker specs, notifications</span></summary>
      <CandleIngestion />
      <DataReadiness />
      </details>
    </div>}

    {page === "system" && <div className="dashboard-group system-workspace">
      <div className="group-heading"><div className="eyebrow">SYSTEM CONFIGURATION</div><h2>Broker & notification services</h2><p>A live operational view of terminal connectivity, telemetry freshness, broker reference data and the event pipeline.</p></div>
      <div className="system-status-grid">
        <article className={overview?.bridge_connected ? "system-status-card pass" : "system-status-card attention"}><span>MT5 BRIDGE</span><b>{overview ? (overview.bridge_connected ? "CONNECTED" : "DISCONNECTED") : "LOADING"}</b><small>{overview?.environment ? "Environment: " + overview.environment : "Awaiting environment report"}</small></article>
        <article className={overview?.heartbeat?.fresh ? "system-status-card pass" : "system-status-card attention"}><span>TERMINAL HEARTBEAT</span><b>{overview?.heartbeat ? (overview.heartbeat.fresh ? "FRESH" : "STALE") : "NOT REPORTED"}</b><small>{overview?.heartbeat?.age_seconds != null ? Math.round(overview.heartbeat.age_seconds) + " seconds since last heartbeat" : "No heartbeat age available"}</small></article>
        <article className={overview?.account?.fresh ? "system-status-card pass" : "system-status-card attention"}><span>ACCOUNT TELEMETRY</span><b>{overview?.account ? (overview.account.fresh ? "FRESH" : "STALE") : "NOT REPORTED"}</b><small>{overview?.account?.observed_at ? "Observed " + stamp(overview.account.observed_at) : "No account snapshot timestamp"}</small></article>
        <article className={(overview?.quotes?.length ?? 0) > 0 && (overview?.quotes ?? []).every(quote => quote.fresh) ? "system-status-card pass" : "system-status-card attention"}><span>MARKET QUOTES</span><b>{overview ? (overview.quotes.filter(quote => quote.fresh).length + " / " + overview.quotes.length + " FRESH") : "LOADING"}</b><small>Fresh quotes / reported symbols</small></article>
      </div>
      <div className="system-section-list">
        <details className="dashboard-accordion" open><summary><span className="strategy-step">01</span><span className="strategy-summary-copy"><b>Broker specifications</b><small>Contract sizes, tick values, volume constraints and symbol freshness</small></span><em>Reference data</em></summary><BrokerSpecifications /></details>
        <details className="dashboard-accordion"><summary><span className="strategy-step">02</span><span className="strategy-summary-copy"><b>Notification pipeline</b><small>Outbox queue, delivery outcomes and active persisted alerts</small></span><em>Service health</em></summary><NotificationHealth /></details>
      </div>
    </div>}

    {page === "strategies" && <div id="strategy" className="dashboard-group strategies-workspace">
      <div className="group-heading"><div className="eyebrow">STRATEGY & PERFORMANCE</div><h2>Research results and trade evidence</h2><p>Move from historical simulation to robustness checks, cross-market comparison and broker-confirmed demo evidence. Each workspace can be opened independently.</p></div>
      <div className="strategy-workflow" aria-label="Research workflow">
        <div><span>01</span><b>Test</b><small>Historical simulation</small></div>
        <i aria-hidden="true">→</i>
        <div><span>02</span><b>Stress</b><small>Transaction costs</small></div>
        <i aria-hidden="true">→</i>
        <div><span>03</span><b>Compare</b><small>Markets and timeframes</small></div>
        <i aria-hidden="true">→</i>
        <div><span>04</span><b>Observe</b><small>Broker demo evidence</small></div>
      </div>
      <div className="strategy-panel-list">
        <details className="dashboard-accordion strategy-accordion"><summary><span className="strategy-step">01</span><span className="strategy-summary-copy"><b>Strategy performance lab</b><small>Backtest, equity curve, drawdown and walk-forward validation</small></span><em>Historical research</em></summary><StrategyPerformance /></details>
        <details className="dashboard-accordion strategy-accordion"><summary><span className="strategy-step">02</span><span className="strategy-summary-copy"><b>Execution cost stress lab</b><small>Compare baseline, moderate, high and severe cost assumptions</small></span><em>Robustness check</em></summary><CostSensitivity /></details>
        <details className="dashboard-accordion strategy-accordion"><summary><span className="strategy-step">03</span><span className="strategy-summary-copy"><b>Cross-market comparison</b><small>Ranked research grid and walk-forward qualification checks</small></span><em>Research ranking</em></summary><StrategyComparison /></details>
        <details className="dashboard-accordion strategy-accordion"><summary><span className="strategy-step">04</span><span className="strategy-summary-copy"><b>Demo observation centre</b><small>Broker-reported orders, deals and terminal snapshots</small></span><em>Broker evidence</em></summary><DemoObservation /></details>
        <details className="dashboard-accordion strategy-accordion"><summary><span className="strategy-step">05</span><span className="strategy-summary-copy"><b>Realized P&amp;L & trade attribution</b><small>Closed-cycle results using complete broker cash components</small></span><em>Demo performance</em></summary><TradeAttribution /></details>
      </div>
      <p className="strategy-disclaimer">Research simulations, cross-market rankings and broker-reported demo results are separate evidence types. Historical results are not live performance, incomplete broker records are excluded from complete-only P&amp;L, and no panel submits orders.</p>
    </div>}

    {page === "risk" && <div id="operations" className="dashboard-group risk-workspace">
    <div className="group-heading"><div className="eyebrow">OPERATIONS & SAFETY</div><h2>Execution oversight and operational continuity</h2><p>Understand the current protection posture, investigate exceptions and review what evidence is still required.</p></div>
    <div className="risk-posture-banner">
      <div className="risk-posture-icon"><ShieldCheck size={21}/></div>
      <div><b>READ-ONLY SAFETY POSTURE</b><span>Execution disabled · Live trading unavailable · No automatic position changes or command retries</span></div>
      <Status good={operations?.read_only === true && operations?.trading_enabled === false}>PROTECTED MODE</Status>
    </div>
    <div className="risk-status-grid">
      <article className={operations?.portfolio_risk_gate.approved ? "risk-status-card pass" : "risk-status-card attention"}><span>PORTFOLIO RISK GATE</span><b>{operations ? (operations.portfolio_risk_gate.approved ? "APPROVED" : "BLOCKED / UNVERIFIED") : "LOADING"}</b><small>{operations?.portfolio_risk_gate.aggregate_stop_risk_pct == null ? "Aggregate stop risk unavailable" : operations.portfolio_risk_gate.aggregate_stop_risk_pct.toFixed(3) + "% aggregate stop risk"}</small></article>
      <article className={operations?.reconciliation.status === "reconciled" ? "risk-status-card pass" : "risk-status-card attention"}><span>POSITION RECONCILIATION</span><b>{operations?.reconciliation.status?.replaceAll("_"," ").toUpperCase() ?? "LOADING"}</b><small>{operations?.reconciliation.orphaned_positions.length ?? "—"} unmatched position(s) · {operations?.reconciliation.protection_issues?.length ?? "—"} protection issue(s)</small></article>
      <article className={recovery?.backups.fresh_verified_backup && recovery?.backups.invalid_count === 0 ? "risk-status-card pass" : "risk-status-card attention"}><span>RECOVERY READINESS</span><b>{recovery?.backups.status?.replaceAll("_"," ").toUpperCase() ?? "LOADING"}</b><small>{recovery?.backups.fresh_verified_backup ? "Fresh verified backup available" : "Fresh verified backup not confirmed"}</small></article>
      <article className={releaseReadiness?.status === "ready" ? "risk-status-card pass" : "risk-status-card attention"}><span>RELEASE READINESS</span><b>{releaseReadiness?.status?.replaceAll("_"," ").toUpperCase() ?? "LOADING"}</b><small>{releaseReadiness ? releaseReadiness.automated_passed + "/" + releaseReadiness.automated_total + " automated checks passed · " + releaseReadiness.manual_validation_required + " manual checks remain" : "Awaiting readiness evidence"}</small></article>
    </div>
    <details className="dashboard-accordion"><summary>Open detailed operations and safety evidence <span>4 panels · risk gate, recovery, reconciliation, release readiness</span></summary>
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


    </details>

    </div>}

    {page === "system" && <details className="dashboard-accordion system-event-accordion"><summary><span className="strategy-step">03</span><span className="strategy-summary-copy"><b>Operations journal</b><small>Search durable events, severity and notification delivery history</small></span><em>{events.length} recent events</em></summary><section id="events" className="panel">
      <div className="section-head"><div><div className="eyebrow">OPERATIONS JOURNAL</div><h2>Recent system events</h2><p className="subhead">Durable event history and notification queue status. No external messages are sent by this view.</p></div><span className="research-tag">{events.length} RECENT</span></div>
      <div className="event-tools">
        <label className="event-search"><span>Search events</span><input type="search" value={eventSearch} onChange={event => setEventSearch(event.target.value)} placeholder="Search message, type or delivery…" /></label>
        <label className="event-filter"><span>Severity</span><select value={eventSeverity} onChange={event => setEventSeverity(event.target.value)}><option value="all">All severities</option><option value="critical">Critical</option><option value="warning">Warning</option><option value="error">Error</option><option value="info">Info</option></select></label>
        <div className="event-result-count">{filteredEvents.length} of {events.length} events</div>
        {(eventSearch || eventSeverity !== "all") && <button className="event-reset" type="button" onClick={() => { setEventSearch(""); setEventSeverity("all"); }}>Clear filters</button>}
      </div>
      <div className="table-wrap"><table><thead><tr><th>TIME</th><th>SEVERITY</th><th>EVENT</th><th>DETAIL</th><th>DELIVERY</th><th>ATTEMPTS</th></tr></thead><tbody>
        {filteredEvents.map(event => <tr key={event.event_id}><td>{stamp(event.occurred_at)}</td><td><Status good={event.severity === "info"}>{event.severity.toUpperCase()}</Status></td><td className="symbol">{event.event_type}</td><td>{event.message}</td><td>{event.delivery_status}</td><td>{event.attempts}</td></tr>)}
        {!events.length && <tr><td colSpan={6} className="empty">No operational events have been recorded yet.</td></tr>}
        {events.length > 0 && !filteredEvents.length && <tr><td colSpan={6} className="empty">No events match these filters. Try another search or clear the filters.</td></tr>}
      </tbody></table></div>
    </section></details>}

    {notificationsOpen && <div className="notification-backdrop" onClick={() => setNotificationsOpen(false)}>
      <aside className="notification-drawer" role="dialog" aria-modal="true" aria-label="System notifications" onClick={event => event.stopPropagation()}>
        <div className="notification-head"><div><div className="eyebrow">LIVE SYSTEM MESSAGES</div><h2>Notifications</h2><p>{alerts.length} active alert{alerts.length === 1 ? "" : "s"} · refreshed with dashboard telemetry</p></div><button ref={notificationCloseRef} type="button" className="drawer-close" aria-label="Close notifications" onClick={() => setNotificationsOpen(false)}>×</button></div>
        {alerts.length > 0 ? <div className="notification-list">{alerts.map((alert, index) => <article className="notification-item" key={index}><div className="notification-symbol"><AlertTriangle size={16}/></div><div><b>{alert.severity ?? "NOTICE"}</b><p>{alert.message ?? "System alert"}</p><small>Current system health report</small></div></article>)}</div> : <div className="notification-empty"><div className="notification-check"><ShieldCheck size={23}/></div><b>No active alerts reported</b><p>This means the latest health response contains no alerts. It does not replace the separate telemetry freshness checks.</p></div>}
        <div className="notification-foot"><span>Critical alerts remain visible on the dashboard.</span><button type="button" onClick={() => { setNotificationsOpen(false); setPage("system"); }}>Open System Centre →</button></div>
      </aside>
    </div>}
    <footer><span><ShieldCheck size={14}/> READ-ONLY DASHBOARD · EXECUTION DISABLED</span><span>Last refreshed: {stamp(lastUpdated)}</span></footer>
  </main>;
}

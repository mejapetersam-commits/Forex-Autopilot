export interface DashboardOverview {
  environment: string;
  execution_mode: string;
  trading_enabled: boolean;
  bridge_connected: boolean;
  heartbeat: { observed_at?: string; age_seconds?: number; fresh: boolean } | null;
  account: {
    balance?: number;
    equity?: number;
    free_margin?: number;
    account_currency?: string;
    observed_at?: string;
    fresh: boolean;
  } | null;
  quotes: Array<{
    symbol: string;
    bid: number;
    ask: number;
    spread?: number;
    observed_at: string;
    age_seconds: number | null;
    fresh: boolean;
  }>;
  system_health: { status?: string; alerts?: Array<{ severity?: string; message?: string }> } | string;
  updated_at: string;
}

export interface ResearchItem {
  symbol: string;
  timeframe: string;
  candles: number;
  signal: string;
  reason: string;
  latest_close: number | null;
  research_status: string;
  data_quality: string;
  gap_count: number;
}

export interface ResearchResponse {
  items: ResearchItem[];
  execution_mode: string;
  trading_enabled: boolean;
  updated_at: string;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export const getOverview = () => getJson<DashboardOverview>("/api/v1/dashboard/overview");
export const getResearch = () => getJson<ResearchResponse>("/api/v1/dashboard/research");

export interface OperationalEvent {
  event_id: string;
  event_type: string;
  severity: "info" | "warning" | "critical";
  message: string;
  occurred_at: string;
  delivery_status: string;
  attempts: number;
}
export interface OperationalEventsResponse {
  items: OperationalEvent[];
  execution_mode: string;
  trading_enabled: boolean;
  updated_at: string;
}
export const getOperationalEvents = () => getJson<OperationalEventsResponse>("/api/v1/dashboard/events?limit=50");

export interface PortfolioCurrency {
  currency: string;
  net_exposure: number;
  gross_exposure: number;
  net_exposure_pct_equity: number;
  gross_exposure_pct_equity: number;
}
export interface PortfolioPosition {
  ticket: string;
  symbol: string;
  side: string;
  volume_lots: number;
  mark_price: number;
  stop_loss: number | null;
  notional_account_currency: number;
  estimated_stop_risk: number | null;
}
export interface PortfolioResponse {
  status: string;
  reasons?: string[];
  positions: PortfolioPosition[];
  currencies: PortfolioCurrency[];
  open_position_count: number;
  total_open_stop_risk: number | null;
  account_equity: number | null;
  account_currency: string | null;
  execution_mode: string;
  trading_enabled: boolean;
  updated_at: string;
}
export const getPortfolio = () => getJson<PortfolioResponse>("/api/v1/dashboard/portfolio");

export interface DashboardOperations {
  reconciliation: {
    status: string;
    managed_positions_checked: number;
    orphaned_positions: Array<{
      ticket: string; position_id: string; symbol: string; side: string;
      volume_lots: number; reason: string;
    }>;
  };
  lifecycle: {
    status: string;
    previous_snapshot_available: boolean;
    managed_positions_current: number;
    events: Array<Record<string, string | number | boolean | null>>;
  };
  portfolio_risk_gate: {
    approved: boolean;
    aggregate_stop_risk_pct: number | null;
    max_stop_risk_pct: number;
    reasons: string[];
  };
  recent_position_events: OperationalEvent[];
  execution_mode: string;
  trading_enabled: boolean;
  read_only: boolean;
  updated_at: string;
}
export const getDashboardOperations = () => getJson<DashboardOperations>("/api/v1/dashboard/operations");

export interface StrategyPerformanceResponse {
  symbol: string;
  timeframe: string;
  candles_available: number;
  data_quality: { status: string; issue_count: number; gap_count: number; issues?: string[] };
  pip_size_used: number;
  pip_value_per_lot_used: number;
  pip_value_source: string;
  backtest: {
    status: string;
    initial_equity?: number;
    final_equity?: number;
    net_profit?: number;
    return_pct?: number;
    total_trades?: number;
    winning_trades?: number;
    losing_trades?: number;
    win_rate_pct?: number;
    profit_factor?: number | null;
    expectancy_per_trade?: number;
    max_drawdown_pct?: number;
    mark_to_market_max_drawdown_pct?: number;
    mark_to_market_equity_curve?: Array<{ time: string | null; equity: number; drawdown_pct: number }>;
    assumptions?: Record<string, string | number | boolean>;
    research_status?: string;
  };
  analytics: {
    median_trade_pnl: number;
    best_trade_pnl: number;
    worst_trade_pnl: number;
    payoff_ratio: number | null;
    max_consecutive_wins: number;
    max_consecutive_losses: number;
    interpretation: string;
  } | null;
  walk_forward: null | {
    status: string;
    candles_available?: number;
    minimum_required?: number;
    out_of_sample_summary?: {
      valid_folds: number;
      total_trades: number;
      mean_return_pct: number | null;
      mean_profit_factor: number | null;
      worst_drawdown_pct: number | null;
    };
    folds?: Array<{
      fold: number;
      training_metrics: Record<string, number | null>;
      out_of_sample_metrics: Record<string, number | string | null>;
      selected_parameters: Record<string, number>;
    }>;
    methodology?: { warning?: string };
  };
  trading_enabled: false;
  execution_mode: string;
  updated_at: string;
}
export const getStrategyPerformance = (symbol: string, timeframe: string, walkForward = false) =>
  getJson<StrategyPerformanceResponse>(`/api/v1/dashboard/strategy-performance?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&include_walk_forward=${walkForward}`);

export interface StrategyComparisonItem {
  symbol: string;
  timeframe: string;
  candles_available: number;
  data_quality: string;
  gap_count: number;
  status: string;
  research_rank?: number;
  return_pct?: number | null;
  total_trades?: number | null;
  win_rate_pct?: number | null;
  profit_factor?: number | null;
  max_drawdown_pct?: number | null;
  expectancy_per_trade?: number | null;
  reason?: string;
}
export interface StrategyComparisonResponse {
  items: StrategyComparisonItem[];
  ranked_count: number;
  ranking_method: string;
  warning: string;
  trading_enabled: false;
  execution_mode: string;
  updated_at: string;
}
export const getStrategyComparison = () =>
  getJson<StrategyComparisonResponse>("/api/v1/dashboard/strategy-comparison");

export interface StrategyQualificationResponse {
  symbol: string;
  timeframe: string;
  candles_available: number;
  qualification: {
    status: string;
    eligible_for_demo_observation: boolean;
    checks: Record<string, string | number | null>;
    thresholds: Record<string, number>;
    reasons: string[];
    disclaimer: string;
  };
  execution_mode: string;
  trading_enabled: false;
  updated_at: string;
}
export const getStrategyQualification = (symbol: string, timeframe: string) =>
  getJson<StrategyQualificationResponse>(`/api/v1/dashboard/strategy-qualification?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}`);

export interface DemoObservationResponse {
  status: string;
  deal_totals: {
    deal_count: number;
    cash_complete_deal_count: number;
    terminal_count: number;
    strategy_magic_count: number;
    first_deal_at: string | null;
    last_observed_at: string | null;
  };
  order_totals: {
    order_count: number;
    completed_orders: number | null;
    failed_orders: number | null;
    last_order_observed_at: string | null;
  };
  groups: Array<{
    magic: number;
    symbol: string;
    entry_deals: number;
    exit_deals: number;
    deal_count: number;
    gross_deal_volume_lots: number;
    last_deal_at: string;
    last_observed_at: string;
  }>;
  latest_terminal: null | {
    terminal_id: string;
    environment: string;
    server: string;
    observed_at: string;
    reported_open_positions: number;
    daily_loss_pct_estimate: number;
  };
  pnl_available: boolean;
  limitations: string[];
  execution_mode: string;
  trading_enabled: false;
  read_only: true;
  updated_at: string;
}
export const getDemoObservation = () => getJson<DemoObservationResponse>("/api/v1/dashboard/demo-observation");

export interface TradeAttributionResponse {
  status: string;
  deal_count: number;
  closed_trade_count: number;
  pnl_complete_trade_count: number;
  pnl_incomplete_trade_count: number;
  unmatched_deal_count: number;
  overclose_or_ambiguous_count: number;
  open_position_count: number;
  missing_cash_deal_count: number;
  net_realized_pnl: number;
  account_currency: string | null;
  win_rate_pct: number | null;
  profit_factor: number | null;
  expectancy_per_trade: number | null;
  average_win: number | null;
  average_loss: number | null;
  max_drawdown_cash: number | null;
  coverage: string;
  groups: Array<{
    magic: number; symbol: string; closed_trade_count: number;
    pnl_complete_trade_count: number; pnl_incomplete_trade_count: number;
    net_realized_pnl: number; win_rate_pct: number | null;
    profit_factor: number | null; expectancy_per_trade: number | null;
    open_position_count: number; unmatched_deal_count: number;
  }>;
  closed_trades: Array<Record<string, string | number | boolean | null>>;
  open_positions: Array<Record<string, string | number>>;
  limitations: string[];
  execution_mode: string;
  trading_enabled: false;
  read_only: true;
  updated_at: string;
}
export const getTradeAttribution = () =>
  getJson<TradeAttributionResponse>("/api/v1/dashboard/trade-attribution");

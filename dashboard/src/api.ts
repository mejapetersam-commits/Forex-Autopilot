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

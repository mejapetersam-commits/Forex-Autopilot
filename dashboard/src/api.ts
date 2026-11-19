export interface DashboardOverview {
  environment: string;
  execution_mode: string;
  trading_enabled: boolean;
  bridge_connected: boolean;
  heartbeat: { observed_at?: string; age_seconds?: number; fresh: boolean } | null;
  account: {
    balance?: number;
    equity?: number;
    margin_free?: number;
    currency?: string;
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

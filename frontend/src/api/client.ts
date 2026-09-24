// Typed API client. All market data comes from the backend; no keys here.

export interface AccountInfo {
  id: string;
  display_name: string;
  start_date: string;
  starting_cash: number;
  benchmarks: string[];
}

export interface Freshness {
  last_refresh_at: string | null;
  last_refresh_status: string | null;
  as_of_date: string | null;
  as_of_provisional: boolean;
  symbols_tracked: number;
  symbols_ok: number;
  symbol_errors: { ticker: string; error: string }[];
  coverage_pct: number | null;
}

export interface Summary {
  account: string;
  empty?: boolean;
  inception: string;
  current_value: number;
  invested_capital: number;
  cash: number;
  positions_value: number;
  today: { dollar: number | null; pct: number | null };
  total: { dollar: number; pct: number | null };
  twr: number | null;
  xirr: number | null;
  benchmarks: Record<string, { twr: number | null; excess: number | null; value: number | null }>;
  risk: {
    beta: number | null;
    beta_min_obs: number;
    cagr: number | null;
    alpha: number | null;
    volatility: number | null;
    sharpe: number | null;
    sortino: number | null;
    max_drawdown: number | null;
    observations: number;
  };
  concentration: {
    largest_position: { ticker: string; weight: number } | null;
    top5: number | null;
    top10: number | null;
    top20: number | null;
    effective_holdings: number | null;
    num_holdings: number;
  };
  freshness: Freshness;
}

export interface Series {
  dates: string[];
  values: number[];
}

export interface Performance {
  account: string;
  inception: string;
  value: Series;
  daily_returns: Series;
  cumulative_returns: Series;
  growth_of_100: Record<string, Series>;
  benchmark_values: Record<string, Series>;
  drawdown: Series;
  benchmark_drawdown: Record<string, Series>;
  rolling: Record<
    string,
    { beta_spy: Series; volatility: Series; corr_spy: Series; corr_qqq: Series }
  >;
  period_returns: Record<string, Record<string, number | null>>;
  calendar_heatmap: Series;
  monthly_heatmap: { year: number; month: number; return: number }[];
}

export interface Holding {
  ticker: string;
  sector: string;
  composite_score: number | null;
  shares: number;
  cost_basis: number | null;
  avg_cost: number | null;
  fill_price: number | null;
  price: number | null;
  price_as_of: string | null;
  price_stale: boolean;
  market_value: number;
  weight: number;
  day_return: number | null;
  day_dollar: number | null;
  unrealized_dollar: number | null;
  unrealized_pct: number | null;
  beta: number | null;
  beta_contribution: number | null;
  target_weight: number | null;
}

export interface HoldingsResponse {
  account: string;
  holdings: Holding[];
  inactive: { ticker: string; sector: string; composite_score: number | null; note: string }[];
}

export interface Allocation {
  account: string;
  empty?: boolean;
  sector_allocation: { sector: string; value: number; weight: number }[];
  concentration_curve: { rank: number; ticker: string; weight: number; cumulative: number }[];
  drift: { ticker: string; current: number; target: number; drift: number }[];
  top_holdings: { ticker: string; value: number; weight: number }[];
  contribution: {
    daily: { ticker: string; sector: string; contribution: number }[];
    cumulative: { ticker: string; sector: string; contribution: number }[];
    daily_by_sector: { sector: string; contribution: number }[];
    cumulative_by_sector: { sector: string; contribution: number }[];
  };
  cash: number;
}

export interface RiskComparisonRow {
  beta_spy: number | null;
  alpha_spy: number | null;
  r_squared_spy: number | null;
  correlation_spy: number | null;
  information_ratio_spy: number | null;
  cagr: number | null;
  volatility: number | null;
  sharpe: number | null;
  sortino: number | null;
  calmar: number | null;
  max_drawdown: number | null;
  observations: number;
}

export interface FactorExposureRow {
  ticker: string;
  label: string;
  beta: number | null;
  correlation: number | null;
}

export interface CorrelationMatrix {
  tickers: string[];
  matrix: number[][];
  observations: number;
}

export interface DiversificationInfo {
  tickers: string[];
  observations: number;
  effective_bets: number;
  num_holdings: number;
  variance_explained: { component: number; variance_pct: number }[];
  pc1_loadings: { ticker: string; loading: number }[];
}

export interface RiskResponse {
  account: string;
  observations: number;
  min_obs: { beta: number; volatility: number; var: number };
  comparison: { portfolio: RiskComparisonRow; spy: RiskComparisonRow; qqq: RiskComparisonRow };
  beta_spy: number | null;
  beta_qqq: number | null;
  correlation_spy: number | null;
  correlation_qqq: number | null;
  volatility: number | null;
  downside_deviation: number | null;
  sharpe: number | null;
  sortino: number | null;
  max_drawdown: number | null;
  var_95: number | null;
  cvar_95: number | null;
  var_99: number | null;
  cvar_99: number | null;
  risk_free_rate: number;
  weighted_security_beta: number | null;
  beta_contributions: { ticker: string; weight: number; beta: number; contribution: number }[];
  risk_contributions: { ticker: string; contribution: number }[];
  risk_contributions_by_sector: { sector: string; contribution: number }[];
  factor_exposure: FactorExposureRow[];
  correlation_matrix: CorrelationMatrix | null;
  diversification: DiversificationInfo | null;
  trailing_window: { target_trading_days: number; observations: number };
}

export interface HeatmapResponse {
  account: string;
  period: string;
  periods: string[];
  tiles: { ticker: string; sector: string; weight: number; value: number; return: number | null }[];
  sectors: { sector: string; weight: number; return: number | null }[];
}

export interface Txn {
  id: number;
  account_id: string;
  trade_date: string;
  ticker: string | null;
  type: string;
  shares: number | null;
  price: number | null;
  fees: number;
  cash_flow: number | null;
  split_ratio: number | null;
  new_ticker: string | null;
  source: string;
  notes: string | null;
}

export interface DataQuality {
  symbols: number;
  issues: { type: string; ticker: string | null; detail: string }[];
  stale_symbols: { ticker: string; last_success_date: string | null; status: string; error: string | null }[];
  refresh_runs: {
    id: number;
    trigger: string;
    status: string;
    started_at: string | null;
    finished_at: string | null;
    symbols_ok: number;
    symbols_failed: number;
    detail: string | null;
  }[];
}

export interface MonteCarloSim {
  tickers: string[];
  dates: string[];
  values: number[];
}

export interface MonteCarloResponse {
  account: string;
  empty?: boolean;
  method?: "equal_weight" | "sector_market_cap_weighted";
  inception: string;
  n_holdings: number;
  universe_size: number;
  sims_requested: number;
  sims_run: number;
  actual: MonteCarloSim;
  simulations: MonteCarloSim[];
  mean: Series;
  median: Series;
  percentile_rank: number | null;
  final_values: { actual: number | null; sims: number[] };
}

export interface RefreshResult {
  run_id: number;
  status: string;
  symbols_total: number;
  symbols_ok: number;
  symbols_failed: number;
  failures: string[];
  dividends_created: number;
  splits_created: number;
}

export interface HistoryHoldingRow {
  ticker: string;
  sector: string;
  shares: number;
  value: number;
  weight: number;
}

export interface HistorySnapshot {
  holdings: HistoryHoldingRow[];
  sector_allocation: { sector: string; weight: number }[];
  cash: number;
  total_value: number;
}

export interface HistoryEvent {
  id: number;
  account_id: string;
  event_date: string;
  notes: string | null;
  before: HistorySnapshot;
  after: HistorySnapshot;
}

export interface ClosedPosition {
  ticker: string;
  open_date: string;
  close_date: string;
  hold_days: number;
  total_cost: number;
  total_proceeds: number;
  gain_dollar: number;
  gain_pct: number | null;
  cagr: number | null;
  spy_cagr: number | null;
  qqq_cagr: number | null;
  cagr_excess_spy: number | null;
  cagr_excess_qqq: number | null;
}

export interface HistoryResponse {
  account: string;
  events: HistoryEvent[];
  closed_positions: ClosedPosition[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

export const api = {
  accounts: () => get<AccountInfo[]>("/api/accounts"),
  summary: (id: string) => get<Summary>(`/api/accounts/${id}/summary`),
  performance: (id: string, start?: string, end?: string) => {
    const q = new URLSearchParams();
    if (start) q.set("start", start);
    if (end) q.set("end", end);
    const qs = q.toString();
    return get<Performance>(`/api/accounts/${id}/performance${qs ? `?${qs}` : ""}`);
  },
  holdings: (id: string) => get<HoldingsResponse>(`/api/accounts/${id}/holdings`),
  allocation: (id: string) => get<Allocation>(`/api/accounts/${id}/allocation`),
  risk: (id: string) => get<RiskResponse>(`/api/accounts/${id}/risk`),
  heatmap: (id: string, period: string) =>
    get<HeatmapResponse>(`/api/accounts/${id}/heatmap?period=${period}`),
  transactions: (id: string) =>
    get<{ account: string; transactions: Txn[] }>(`/api/accounts/${id}/transactions`),
  history: (id: string) => get<HistoryResponse>(`/api/accounts/${id}/history`),
  contributions: () =>
    get<{ accounts: { account: string; value: number; invested: number; gain: number; twr: number | null }[] }>(
      "/api/accounts/combined/contributions",
    ),
  monteCarlo: (id: string, sims: number, seed?: number) => {
    const q = new URLSearchParams({ sims: String(sims) });
    if (seed !== undefined) q.set("seed", String(seed));
    return get<MonteCarloResponse>(`/api/accounts/${id}/monte-carlo?${q.toString()}`);
  },
  dataQuality: () => get<DataQuality>("/api/data-quality"),
  refresh: async (): Promise<RefreshResult> => {
    const res = await fetch("/api/refresh", { method: "POST" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body.detail ?? res.statusText);
    }
    return res.json();
  },
  exportUrl: (id: string) => `/api/accounts/${id}/transactions/export`,
  importTransactions: async (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`/api/accounts/${id}/transactions/import`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body.detail ?? res.statusText);
    }
    return res.json() as Promise<{ created: number; skipped: number; errors: string[]; committed: boolean }>;
  },
};

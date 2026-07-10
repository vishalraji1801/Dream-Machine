// API client — token auth + typed calls to the FastAPI backend.
// The token lives in localStorage and rides on every request as X-API-Token.

const TOKEN_KEY = "dm_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY) || "";
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t.trim());
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-API-Token": getToken(),
      ...(init.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

// ── types ────────────────────────────────────────────────────────────────────

export interface Position {
  symbol: string;
  direction: string;
  entry_price: number;
  quantity: number;
  stop_loss: number;
  target: number;
  entry_time?: string;
}

export interface PositionsResp {
  positions: Position[];
  daily_pnl: number;
  trades_today: number;
  date: string | null;
  stale: boolean;
}

export interface Status {
  mode: "paper" | "live";
  market?: string;
  token_fresh_today?: boolean;
  paper_trades?: number;
  paper_net_pnl?: number;
  gate_ready?: boolean;
  gate_checks?: Record<string, boolean>;
}

export interface ControlState {
  running: boolean;
  pid: number | null;
  mode: "paper" | "live";
}

export interface Trade {
  symbol: string;
  direction: string;
  quantity: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  exit_reason?: string;
  exit_time?: string;
}

export interface Signal {
  ts: string;
  symbol: string;
  direction: string;
  taken: number;
  reason?: string;
}

export interface Equity {
  snapshots: { ts: string; daily_pnl: number }[];
  trade_curve: { exit_time: string; symbol: string; pnl: number; cumulative: number }[];
  net_pnl: number;
  trade_count: number;
}

export interface ConfigField {
  key: string;
  label: string;
  type: "number" | "bool" | "select" | "time" | "text";
  min: number | null;
  max: number | null;
  step: number | null;
  unit: string;
  options: string[];
  help: string;
  value: number | boolean | string | null;
}

export interface ConfigGroup {
  section: string;
  label: string;
  fields: ConfigField[];
}

export interface BacktestData {
  timeframes: Record<string, { symbols: number; sample: string[] }>;
}

export interface BacktestAggregate {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  net_pnl: number;
  profit_factor: number | null;
  gross_profit: number;
  gross_loss: number;
  symbols_tested: number;
}

export interface BacktestSymbolRow {
  symbol: string;
  total_trades: number;
  net_pnl: number;
  win_rate: number;
  profit_factor: number | null;
  max_drawdown: number;
}

export interface BacktestJob {
  status: "running" | "done" | "error";
  result: { aggregate: BacktestAggregate; per_symbol: BacktestSymbolRow[] } | null;
  error: string | null;
  strategy?: string;
  timeframe?: string;
}

export interface StrategiesResp {
  registered: string[];
  active: string;
  allowed: string[];
}

// ── calls ────────────────────────────────────────────────────────────────────

export const api = {
  health: () => req<{ ok: boolean; token_configured: boolean }>("/api/health"),
  status: () => req<Status>("/api/status"),
  positions: () => req<PositionsResp>("/api/positions"),
  trades: (source?: string) =>
    req<{ count: number; trades: Trade[] }>(`/api/trades${source ? `?source=${source}` : ""}`),
  signals: () => req<{ count: number; signals: Signal[] }>("/api/signals"),
  equity: (source?: string) =>
    req<Equity>(`/api/equity${source ? `?source=${source}` : ""}`),
  controlState: () => req<ControlState>("/api/control/state"),
  start: (confirmLive = false) =>
    req("/api/control/start", { method: "POST", body: JSON.stringify({ confirm_live: confirmLive }) }),
  stop: () => req("/api/control/stop", { method: "POST" }),
  pause: () => req("/api/control/pause", { method: "POST" }),
  resume: () => req("/api/control/resume", { method: "POST" }),
  squareoff: () => req("/api/control/squareoff", { method: "POST" }),
  getConfig: () => req<{ groups: ConfigGroup[] }>("/api/config"),
  putConfig: (updates: Record<string, Record<string, unknown>>) =>
    req<{ saved: boolean; applies: string; groups: ConfigGroup[] }>("/api/config", {
      method: "PUT",
      body: JSON.stringify({ updates }),
    }),
  backtestData: () => req<BacktestData>("/api/backtest/data"),
  runBacktest: (body: {
    strategy: string;
    timeframe: string;
    window: number;
    overrides?: Record<string, unknown>;
  }) => req<{ job_id: string }>("/api/backtest", { method: "POST", body: JSON.stringify(body) }),
  backtestJob: (id: string) => req<BacktestJob>(`/api/backtest/${id}`),
  strategies: () => req<StrategiesResp>("/api/strategies"),
  setActiveStrategy: (name: string) =>
    req<{ active: string; applies: string }>("/api/strategies/active", {
      method: "PUT",
      body: JSON.stringify({ name }),
    }),
};

// Verify a token by calling a protected endpoint; returns true if accepted.
export async function verifyToken(): Promise<boolean> {
  try {
    await api.status();
    return true;
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 503)) return false;
    return false;
  }
}

import { useEffect, useRef, useState } from "react";
import { api, ApiError, type BacktestData, type BacktestJob, type StrategiesResp } from "../api";
import { inr, pnlColor } from "../util";

export default function Backtest() {
  const [data, setData] = useState<BacktestData | null>(null);
  const [strats, setStrats] = useState<StrategiesResp | null>(null);
  const [strategy, setStrategy] = useState("");
  const [timeframe, setTimeframe] = useState("15min");
  const [window, setWindow] = useState(60);
  const [regime, setRegime] = useState(false);
  const [job, setJob] = useState<BacktestJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    api.backtestData().then((d) => {
      setData(d);
      const tfs = Object.keys(d.timeframes);
      if (tfs.length && !tfs.includes("15min")) setTimeframe(tfs[0]);
    }).catch(() => {});
    api.strategies().then((s) => {
      setStrats(s);
      setStrategy(s.active);
    }).catch(() => {});
    return () => {
      if (poll.current) clearInterval(poll.current);
    };
  }, []);

  const run = async () => {
    setBusy(true);
    setErr("");
    setJob(null);
    try {
      const { job_id } = await api.runBacktest({
        strategy,
        timeframe,
        window,
        overrides: { regime_filter_enabled: regime },
      });
      poll.current = setInterval(async () => {
        const j = await api.backtestJob(job_id);
        setJob(j);
        if (j.status !== "running" && poll.current) {
          clearInterval(poll.current);
          setBusy(false);
        }
      }, 1000);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
      setBusy(false);
    }
  };

  const tfs = data ? Object.keys(data.timeframes) : [];
  const noData = data && tfs.length === 0;
  const agg = job?.result?.aggregate;

  return (
    <div className="space-y-4">
      <div className="card space-y-4">
        <div className="label">Run backtest</div>
        {noData && (
          <div className="text-sm text-warn">
            No stored candles found. Run the data pipeline first (backtest_run.py).
          </div>
        )}
        {strats && strats.registered.length === 0 && (
          <div className="text-sm text-muted">
            No strategies registered yet — a run will simply produce 0 trades until you add one.
          </div>
        )}
        <div className="grid sm:grid-cols-2 gap-x-6 gap-y-3">
          <Row label="Strategy">
            <select className="ctl" value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              <option value="">(none — no trades)</option>
              {strats?.registered.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
              {strats && strats.active && !strats.registered.includes(strats.active) && (
                <option value={strats.active}>{strats.active} (config)</option>
              )}
            </select>
          </Row>
          <Row label="Timeframe">
            <select className="ctl" value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {tfs.map((tf) => (
                <option key={tf} value={tf}>
                  {tf} · {data!.timeframes[tf].symbols} symbols
                </option>
              ))}
            </select>
          </Row>
          <Row label="Warmup window (bars)">
            <input
              type="number"
              className="ctl w-28 text-right font-mono"
              min={20}
              max={400}
              value={window}
              onChange={(e) => setWindow(Number(e.target.value))}
            />
          </Row>
          <Row label="Regime filter">
            <input
              type="checkbox"
              className="w-5 h-5 accent-accent"
              checked={regime}
              onChange={(e) => setRegime(e.target.checked)}
            />
          </Row>
        </div>
        <button className="btn btn-accent" disabled={busy || !!noData} onClick={run}>
          {busy ? "Running…" : "Run backtest"}
        </button>
        {err && <div className="text-down text-sm">{err}</div>}
      </div>

      {job?.status === "error" && (
        <div className="card text-down text-sm">Backtest failed: {job.error}</div>
      )}

      {agg && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Metric label="Net P&L" value={inr(agg.net_pnl)} className={pnlColor(agg.net_pnl)} />
            <Metric label="Trades" value={String(agg.total_trades)} />
            <Metric label="Win rate" value={`${agg.win_rate}%`} />
            <Metric
              label="Profit factor"
              value={agg.profit_factor === null ? "∞" : String(agg.profit_factor)}
              className={(agg.profit_factor ?? 0) >= 1.2 ? "text-up" : "text-muted"}
            />
          </div>
          <div className="card">
            <div className="label mb-3">Per symbol ({agg.symbols_tested})</div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-muted text-xs text-left">
                  <tr>
                    <th className="py-1 px-1">Symbol</th>
                    <th className="px-1 text-right">Trades</th>
                    <th className="px-1 text-right">Net P&L</th>
                    <th className="px-1 text-right">Win %</th>
                    <th className="px-1 text-right">PF</th>
                    <th className="px-1 text-right">Max DD</th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {job!.result!.per_symbol
                    .filter((r) => r.total_trades > 0)
                    .sort((a, b) => b.net_pnl - a.net_pnl)
                    .map((r) => (
                      <tr key={r.symbol} className="border-t border-line">
                        <td className="py-1.5 px-1 font-sans">{r.symbol}</td>
                        <td className="px-1 text-right">{r.total_trades}</td>
                        <td className={`px-1 text-right ${pnlColor(r.net_pnl)}`}>{inr(r.net_pnl)}</td>
                        <td className="px-1 text-right">{r.win_rate}%</td>
                        <td className="px-1 text-right">{r.profit_factor ?? "∞"}</td>
                        <td className="px-1 text-right text-down">{inr(r.max_drawdown)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
              {agg.total_trades === 0 && (
                <div className="text-sm text-muted py-4 text-center">
                  0 trades — no strategy registered, or none of its conditions triggered.
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center justify-between gap-3">
      <span className="text-sm">{label}</span>
      <span className="shrink-0">{children}</span>
    </label>
  );
}

function Metric({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className={`text-2xl font-semibold mt-1 font-mono ${className}`}>{value}</div>
    </div>
  );
}

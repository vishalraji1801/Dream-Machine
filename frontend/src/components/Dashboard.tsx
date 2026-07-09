import { useCallback, useEffect, useState } from "react";
import { api, type Equity, type Signal } from "../api";
import { useLiveCtx } from "../LiveContext";
import { inr, pnlColor } from "../util";
import Controls from "./Controls";
import Positions from "./Positions";
import EquityChart from "./EquityChart";
import Signals from "./Signals";

function Stat({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className={`text-2xl font-semibold mt-1 font-mono ${className}`}>{value}</div>
    </div>
  );
}

export default function Dashboard() {
  const { snap, status, ctl, running, mode, refresh } = useLiveCtx();
  const [equity, setEquity] = useState<Equity | null>(null);
  const [signals, setSignals] = useState<Signal[]>([]);

  const load = useCallback(async () => {
    const [eq, sg] = await Promise.allSettled([api.equity(), api.signals()]);
    if (eq.status === "fulfilled") setEquity(eq.value);
    if (sg.status === "fulfilled") setSignals(sg.value.signals);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  const dailyPnl = snap?.daily_pnl ?? 0;
  const tradesToday = snap?.trades_today ?? 0;
  const positions = snap?.positions ?? [];
  const stale = snap?.stale ?? true;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Daily P&L" value={inr(dailyPnl)} className={pnlColor(dailyPnl)} />
        <Stat label="Trades today" value={String(tradesToday)} />
        <Stat label="Net P&L (all)" value={inr(equity?.net_pnl ?? 0)} className={pnlColor(equity?.net_pnl ?? 0)} />
        <Stat
          label="Go-live gate"
          value={status?.gate_ready ? "READY" : "not yet"}
          className={status?.gate_ready ? "text-up" : "text-muted"}
        />
      </div>

      <Controls state={ctl ?? { running, pid: null, mode }} onChange={refresh} />

      <div className="grid lg:grid-cols-2 gap-4">
        <Positions positions={positions} stale={stale} />
        <EquityChart equity={equity} />
      </div>

      <Signals signals={signals} />

      <footer className="text-center text-xs text-muted py-4">
        {status?.market} · token {status?.token_fresh_today ? "fresh" : "stale"}
      </footer>
    </div>
  );
}

import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Equity } from "../api";
import { inr } from "../util";

export default function EquityChart({ equity }: { equity: Equity | null }) {
  const data = (equity?.trade_curve || []).map((p, i) => ({
    i: i + 1,
    cumulative: p.cumulative,
    symbol: p.symbol,
  }));
  const net = equity?.net_pnl ?? 0;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="label">Cumulative P&L (closed trades)</div>
        <div className={`font-mono ${net > 0 ? "text-up" : net < 0 ? "text-down" : "text-muted"}`}>
          {inr(net)} · {equity?.trade_count ?? 0} trades
        </div>
      </div>
      {data.length === 0 ? (
        <div className="text-sm text-muted py-10 text-center">No closed trades yet</div>
      ) : (
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -16 }}>
              <defs>
                <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#4f8cff" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="#4f8cff" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="i" stroke="#8695ad" fontSize={11} tickLine={false} />
              <YAxis stroke="#8695ad" fontSize={11} tickLine={false} width={48}
                tickFormatter={(v) => inr(v)} />
              <Tooltip
                contentStyle={{ background: "#1a2333", border: "1px solid #243044", borderRadius: 8 }}
                labelStyle={{ color: "#8695ad" }}
                formatter={(v) => [inr(Number(v)), "Cumulative"] as [string, string]}
              />
              <Area type="monotone" dataKey="cumulative" stroke="#4f8cff" fill="url(#eq)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

import type { Position } from "../api";
import { inr2 } from "../util";

export default function Positions({ positions, stale }: { positions: Position[]; stale: boolean }) {
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="label">Open positions ({positions.length})</div>
        {stale && <span className="text-xs text-warn">bot not run today</span>}
      </div>
      {positions.length === 0 ? (
        <div className="text-sm text-muted py-6 text-center">No open positions</div>
      ) : (
        <div className="overflow-x-auto -mx-1">
          <table className="w-full text-sm">
            <thead className="text-muted text-xs">
              <tr className="text-left">
                <th className="py-1 px-1">Symbol</th>
                <th className="px-1">Side</th>
                <th className="px-1 text-right">Qty</th>
                <th className="px-1 text-right">Entry</th>
                <th className="px-1 text-right">SL</th>
                <th className="px-1 text-right">Target</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {positions.map((p, i) => (
                <tr key={i} className="border-t border-line">
                  <td className="py-1.5 px-1 font-sans">{p.symbol}</td>
                  <td className="px-1">
                    <span className={p.direction === "BUY" ? "text-up" : "text-down"}>
                      {p.direction}
                    </span>
                  </td>
                  <td className="px-1 text-right">{p.quantity}</td>
                  <td className="px-1 text-right">{inr2(p.entry_price)}</td>
                  <td className="px-1 text-right text-down">{inr2(p.stop_loss)}</td>
                  <td className="px-1 text-right text-up">{inr2(p.target)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

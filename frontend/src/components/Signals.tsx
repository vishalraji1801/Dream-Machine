import type { Signal } from "../api";
import { time } from "../util";

export default function Signals({ signals }: { signals: Signal[] }) {
  const recent = [...signals].reverse().slice(0, 30);
  return (
    <div className="card">
      <div className="label mb-3">Signal feed</div>
      {recent.length === 0 ? (
        <div className="text-sm text-muted py-6 text-center">No signals yet</div>
      ) : (
        <div className="space-y-1 max-h-72 overflow-y-auto">
          {recent.map((s, i) => (
            <div key={i} className="flex items-center gap-2 text-sm py-1 border-b border-line/50">
              <span className="text-muted text-xs w-12 font-mono">{time(s.ts)}</span>
              <span className={s.direction === "BUY" ? "text-up" : "text-down"}>{s.direction}</span>
              <span className="font-sans">{s.symbol}</span>
              <span className="text-muted text-xs ml-auto truncate max-w-[45%]">{s.reason}</span>
              <span className={`text-xs ${s.taken ? "text-up" : "text-muted"}`}>
                {s.taken ? "taken" : "skipped"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

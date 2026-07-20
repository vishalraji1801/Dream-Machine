import { useEffect, useState } from "react";
import { api, ApiError, type StrategiesResp } from "../api";

export default function Strategies() {
  const [data, setData] = useState<StrategiesResp | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const load = () => api.strategies().then(setData).catch(() => {});
  useEffect(() => {
    load();
  }, []);

  const setActive = async (name: string) => {
    setBusy(name || "(none)");
    setMsg(null);
    try {
      const r = await api.setActiveStrategy(name);
      setMsg({ kind: "ok", text: `Active strategy set to "${r.active || "(none)"}" — ${r.applies}.` });
      await load();
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };

  if (!data) return <div className="text-muted">Loading…</div>;

  const rows = data.registered;
  const swing = data.swing;
  const validatedEdges = swing?.edges?.filter((e) => e.validated) ?? [];
  const benchedEdges = swing?.edges?.filter((e) => !e.validated) ?? [];

  return (
    <div className="space-y-4">
      {/* Sleeve status — the bot is swing-only after the validation gauntlet */}
      <div className="card">
        <div className="label mb-2">Sleeves</div>
        <div className="flex items-center gap-2 py-1">
          <span className="font-mono">Swing (daily, CNC)</span>
          <span className={`text-xs ml-auto ${swing?.enabled ? "text-up" : "text-muted"}`}>
            {swing?.enabled ? "● active" : "off"}
          </span>
        </div>
        <div className="flex items-center gap-2 py-1 border-t border-line">
          <span className="font-mono">Intraday (MIS)</span>
          <span className={`text-xs ml-auto ${data.intraday_enabled ? "text-up" : "text-down"}`}>
            {data.intraday_enabled ? "● active" : "suspended — no validated intraday edge"}
          </span>
        </div>
      </div>

      {/* Validated swing edges (what actually trades) */}
      <div className="card">
        <div className="label mb-3">Validated swing edges ({validatedEdges.length})</div>
        {validatedEdges.length === 0 ? (
          <div className="text-sm text-muted py-4 text-center">None active.</div>
        ) : (
          <div className="space-y-2">
            {validatedEdges.map((e) => (
              <div key={e.name} className="flex items-center gap-3 py-2 border-t border-line first:border-0">
                <span className="font-mono">{e.name}</span>
                {e.pf != null && <span className="text-xs text-muted">PF {e.pf.toFixed(2)}</span>}
                <span className="text-xs text-up ml-auto">● validated</span>
              </div>
            ))}
          </div>
        )}
        {benchedEdges.length > 0 && (
          <div className="mt-3 pt-3 border-t border-line">
            <div className="label mb-2">Benched ({benchedEdges.length})</div>
            {benchedEdges.map((e) => (
              <div key={e.name} className="flex items-center gap-3 py-1 text-sm text-muted">
                <span className="font-mono">{e.name}</span>
                {e.pf != null && <span className="text-xs">PF {e.pf.toFixed(2)}</span>}
                <span className="text-xs ml-auto">benched</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <div className="label mb-1">All registered strategies ({rows.length})</div>
        <div className="text-xs text-muted mb-3">
          Research registry + legacy intraday selector (intraday is currently suspended).
        </div>
        {rows.length === 0 ? (
          <div className="text-sm text-muted py-6 text-center">
            No strategies registered. Add one to <code>STRATEGY_REGISTRY</code> in
            <code> src/strategy.py</code>, then it appears here to select and backtest.
          </div>
        ) : (
          <div className="space-y-2">
            {rows.map((name) => (
              <div key={name} className="flex items-center gap-3 py-2 border-t border-line first:border-0">
                <span className="font-mono">{name}</span>
                {data.active === name ? (
                  <span className="text-xs text-up ml-auto">● active</span>
                ) : (
                  <button
                    className="btn ml-auto"
                    disabled={!!busy}
                    onClick={() => setActive(name)}
                  >
                    {busy === name ? "…" : "Set active"}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
        {data.active && (
          <button
            className="btn mt-3"
            disabled={!!busy}
            onClick={() => setActive("")}
          >
            {busy === "(none)" ? "…" : "Deactivate (no trades)"}
          </button>
        )}
      </div>

      {msg && (
        <div className={`text-sm ${msg.kind === "ok" ? "text-up" : "text-down"}`}>{msg.text}</div>
      )}
    </div>
  );
}

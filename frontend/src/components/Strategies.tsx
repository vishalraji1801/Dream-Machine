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

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="label mb-1">Active strategy</div>
        <div className="text-xl font-semibold">{data.active || "(none — clean slate, no trades)"}</div>
        <div className="text-xs text-muted mt-1">Changes apply on the next bot start.</div>
      </div>

      <div className="card">
        <div className="label mb-3">Registered strategies ({rows.length})</div>
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

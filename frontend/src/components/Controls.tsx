import { useState } from "react";
import { api, ApiError, type ControlState } from "../api";

export default function Controls({
  state,
  onChange,
}: {
  state: ControlState | null;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const running = state?.running ?? false;
  const live = state?.mode === "live";

  const run = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name);
    setErr("");
    try {
      await fn();
      onChange();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const start = () =>
    run("start", async () => {
      try {
        await api.start(false);
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          if (confirm("Bot is in LIVE mode — this places REAL orders. Start anyway?")) {
            await api.start(true);
          } else return;
        } else throw e;
      }
    });

  const squareoff = () =>
    run("squareoff", async () => {
      if (!confirm("Square off ALL open positions now and pause new entries?")) return;
      await api.squareoff();
    });

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="label">Controls</div>
        {live && <span className="text-xs text-down">LIVE — real orders</span>}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        <button className="btn btn-accent" disabled={running || !!busy} onClick={start}>
          {busy === "start" ? "…" : "Start"}
        </button>
        <button className="btn" disabled={!running || !!busy} onClick={() => run("pause", api.pause)}>
          Pause
        </button>
        <button className="btn" disabled={!running || !!busy} onClick={() => run("resume", api.resume)}>
          Resume
        </button>
        <button className="btn btn-danger" disabled={!running || !!busy} onClick={squareoff}>
          Square off
        </button>
        <button className="btn btn-danger" disabled={!running || !!busy} onClick={() => run("stop", api.stop)}>
          {busy === "stop" ? "…" : "Stop"}
        </button>
      </div>
      {err && <div className="text-down text-sm mt-2">{err}</div>}
    </div>
  );
}

import { useState } from "react";
import { setToken, verifyToken } from "../api";

export default function Login({ onAuthed }: { onAuthed: () => void }) {
  const [value, setValue] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    setToken(value);
    const ok = await verifyToken();
    setBusy(false);
    if (ok) onAuthed();
    else setErr("Invalid token, or the backend has no token configured.");
  };

  return (
    <div className="min-h-full grid place-items-center p-6">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4">
        <div>
          <div className="text-lg font-semibold">Dream Machine</div>
          <div className="text-sm text-muted">Enter your API token to connect</div>
        </div>
        <input
          type="password"
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="API token"
          className="w-full bg-panel2 border border-line rounded-lg px-3 py-2 text-sm outline-none focus:border-accent"
        />
        {err && <div className="text-down text-sm">{err}</div>}
        <button className="btn btn-accent w-full" disabled={busy || !value}>
          {busy ? "Connecting…" : "Connect"}
        </button>
        <div className="text-xs text-muted">
          Generate one on the server: <code>python -m webapp gen-token</code>
        </div>
      </form>
    </div>
  );
}

import { useState } from "react";
import { api, ApiError, setToken } from "../api";

export default function Login({ onAuthed }: { onAuthed: () => void }) {
  const [totp, setTotp] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const { token } = await api.login(totp);
      setToken(token);
      onAuthed();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-full grid place-items-center p-6">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4">
        <div>
          <div className="text-lg font-semibold">Dream Machine</div>
          <div className="text-sm text-muted">Enter your Kite TOTP to sign in</div>
        </div>
        <input
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]*"
          maxLength={6}
          autoFocus
          value={totp}
          onChange={(e) => setTotp(e.target.value.replace(/\D/g, ""))}
          placeholder="6-digit code"
          className="w-full bg-panel2 border border-line rounded-lg px-3 py-2 text-center text-2xl tracking-[0.4em] font-mono outline-none focus:border-accent"
        />
        {err && <div className="text-down text-sm">{err}</div>}
        <button className="btn btn-accent w-full" disabled={busy || totp.length < 6}>
          {busy ? "Authenticating with Kite…" : "Sign in"}
        </button>
        <div className="text-xs text-muted">
          Same TOTP as the bot's daily login — your API key and password stay on the server.
          Signing in also refreshes the day's Kite token.
        </div>
      </form>
    </div>
  );
}

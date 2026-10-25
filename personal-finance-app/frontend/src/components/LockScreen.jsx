import { useEffect, useRef, useState } from 'react';

export default function LockScreen({ mode, onUnlock, onSetup, lockoutMs = 0 }) {
  const isSetup = mode === 'setup';
  const [pin, setPin] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [waitLeft, setWaitLeft] = useState(lockoutMs);
  const inputRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, [mode]);

  useEffect(() => setWaitLeft(lockoutMs), [lockoutMs]);

  useEffect(() => {
    if (waitLeft <= 0) return undefined;
    const id = setInterval(() => setWaitLeft((ms) => Math.max(ms - 1000, 0)), 1000);
    return () => clearInterval(id);
  }, [waitLeft]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);

    if (isSetup) {
      if (pin.trim().length < 4) return setError('Use at least 4 characters.');
      if (pin !== confirm) return setError('The two entries do not match.');
    }

    setBusy(true);
    try {
      if (isSetup) await onSetup(pin);
      else await onUnlock(pin);
      setPin('');
      setConfirm('');
    } catch (err) {
      setError(err.message);
      if (typeof err.lockoutMs === 'number') setWaitLeft(err.lockoutMs);
      setPin('');
    } finally {
      setBusy(false);
    }
  }

  const blocked = waitLeft > 0;

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={handleSubmit} className="card w-full max-w-sm p-6">
        <div className="mb-5 text-center">
          <div
            aria-hidden="true"
            className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-xl text-xl"
            style={{ backgroundColor: 'var(--color-raised)' }}
          >
            {isSetup ? '🔑' : '🔒'}
          </div>
          <h1 className="text-base font-semibold">Personal Finance App</h1>
          <p className="mt-1 text-xs text-[var(--color-muted)]">
            {isSetup
              ? 'Choose a PIN or passphrase to protect your finances'
              : 'Enter your PIN to continue'}
          </p>
        </div>

        <div className="space-y-3">
          <div>
            <label className="label" htmlFor="pin">{isSetup ? 'New PIN' : 'PIN'}</label>
            <input
              ref={inputRef}
              id="pin"
              type="password"
              autoComplete={isSetup ? 'new-password' : 'current-password'}
              className="field text-center tracking-[0.3em]"
              value={pin}
              disabled={busy || blocked}
              onChange={(e) => setPin(e.target.value)}
            />
          </div>

          {isSetup ? (
            <div>
              <label className="label" htmlFor="pin-confirm">Confirm</label>
              <input
                id="pin-confirm"
                type="password"
                autoComplete="new-password"
                className="field text-center tracking-[0.3em]"
                value={confirm}
                disabled={busy}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </div>
          ) : null}

          <button type="submit" className="btn btn-primary w-full" disabled={busy || blocked}>
            {blocked
              ? `Locked out — ${Math.ceil(waitLeft / 1000)}s`
              : busy
                ? 'Checking…'
                : isSetup
                  ? 'Set PIN and continue'
                  : 'Unlock'}
          </button>
        </div>

        {error ? (
          <p className="mt-3 text-center text-xs text-[var(--color-critical)]">{error}</p>
        ) : null}

        {isSetup ? (
          <p className="mt-4 border-t border-[var(--color-line)] pt-3 text-[11px] leading-relaxed text-[var(--color-muted)]">
            This locks the app and its local data service. It does not encrypt the database
            file, so anyone with access to your Windows account could still read it directly.
          </p>
        ) : null}
      </form>
    </div>
  );
}

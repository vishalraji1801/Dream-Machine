import { useEffect, useState } from 'react';
import { todayISO } from '../lib/format.js';

const EMPTY = {
  date: todayISO(),
  fund: '',
  type: 'buy',
  amount: '',
  units: '',
  nav: '',
  source: 'bank',
  note: '',
};

const toNum = (v) => {
  if (v === '' || v === null || v === undefined) return null;
  const n = Number(String(v).replace(/[,\s₹]/g, ''));
  return Number.isFinite(n) ? n : null;
};

export default function MutualFundForm({ editing, onSubmit, onCancelEdit, busy, knownFunds }) {
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState([]);

  useEffect(() => {
    setErrors([]);
    setForm(
      editing
        ? {
            date: editing.date,
            fund: editing.fund,
            type: editing.type,
            amount: String(editing.amount),
            units: editing.units == null ? '' : String(editing.units),
            nav: editing.nav == null ? '' : String(editing.nav),
            source: editing.source ?? 'bank',
            note: editing.note ?? '',
          }
        : EMPTY,
    );
  }, [editing]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const amount = toNum(form.amount);
  const units = toNum(form.units);
  const nav = toNum(form.nav);

  // Show what will be derived, so the saved row holds no surprises.
  let derived = null;
  if (amount === null && units !== null && nav) derived = `Amount will be ₹${(units * nav).toFixed(2)}`;
  else if (units === null && amount !== null && nav) derived = `Units will be ${(amount / nav).toFixed(4)}`;
  else if (nav === null && amount !== null && units) derived = `NAV will be ₹${(amount / units).toFixed(4)}`;

  async function handleSubmit(e) {
    e.preventDefault();

    const found = [];
    if (!form.date) found.push('Pick a date.');
    if (!form.fund.trim()) found.push('Enter the fund name.');
    if (amount === null && !(units !== null && nav !== null)) {
      found.push('Give an amount, or units and NAV to work it out from.');
    }

    setErrors(found);
    if (found.length) return;

    try {
      await onSubmit({
        date: form.date,
        fund: form.fund.trim(),
        type: form.type,
        amount: form.amount === '' ? null : amount,
        units: form.units === '' ? null : units,
        nav: form.nav === '' ? null : nav,
        source: form.source,
        note: form.note.trim() || null,
      });
      if (!editing) setForm({ ...EMPTY, date: form.date, fund: form.fund, type: form.type, source: form.source });
    } catch (err) {
      setErrors(err.errors ?? [err.message]);
    }
  }

  const isBuy = form.type === 'buy';

  return (
    <form onSubmit={handleSubmit} className="card p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">
          {editing ? `Edit entry #${editing.id}` : 'Add fund transaction'}
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex overflow-hidden rounded-lg border border-[var(--color-hair)]">
            {[
              { key: 'buy', label: 'Buy' },
              { key: 'sell', label: 'Sell' },
            ].map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setForm((f) => ({ ...f, type: t.key }))}
                aria-pressed={form.type === t.key}
                className="px-3 py-[0.4rem] text-xs font-semibold"
                style={{
                  backgroundColor: form.type === t.key ? 'var(--color-raised)' : 'transparent',
                  color: form.type === t.key ? 'var(--color-ink)' : 'var(--color-muted)',
                }}
              >
                {t.label}
              </button>
            ))}
          </div>
          {isBuy ? (
            <div className="flex overflow-hidden rounded-lg border border-[var(--color-hair)]">
              {[
                { key: 'bank', label: 'From bank' },
                { key: 'lenden', label: 'From LenDen' },
              ].map((s) => (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => setForm((f) => ({ ...f, source: s.key }))}
                  aria-pressed={form.source === s.key}
                  className="px-3 py-[0.4rem] text-xs font-semibold"
                  style={{
                    backgroundColor:
                      form.source === s.key
                        ? s.key === 'lenden'
                          ? 'color-mix(in srgb, var(--color-s3) 20%, transparent)'
                          : 'var(--color-raised)'
                        : 'transparent',
                    color: form.source === s.key ? 'var(--color-ink)' : 'var(--color-muted)',
                  }}
                >
                  {s.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <div className="col-span-2 sm:col-span-1">
          <label className="label" htmlFor="mf-fund">Fund</label>
          <input
            id="mf-fund"
            className="field"
            list="mf-funds"
            placeholder="Parag Flexi Cap"
            value={form.fund}
            onChange={set('fund')}
          />
          <datalist id="mf-funds">
            {knownFunds.map((f) => (
              <option key={f} value={f} />
            ))}
          </datalist>
        </div>
        <div>
          <label className="label" htmlFor="mf-date">Date</label>
          <input id="mf-date" type="date" className="field" value={form.date} onChange={set('date')} />
        </div>
        <div>
          <label className="label" htmlFor="mf-amount">Amount (₹)</label>
          <input id="mf-amount" className="field" inputMode="decimal" placeholder="10000" value={form.amount} onChange={set('amount')} />
        </div>
        <div>
          <label className="label" htmlFor="mf-units">Units</label>
          <input id="mf-units" className="field" inputMode="decimal" placeholder="optional" value={form.units} onChange={set('units')} />
        </div>
        <div>
          <label className="label" htmlFor="mf-nav">NAV (₹)</label>
          <input id="mf-nav" className="field" inputMode="decimal" placeholder="optional" value={form.nav} onChange={set('nav')} />
        </div>
        <div className="flex items-end gap-2">
          <button type="submit" className="btn btn-primary flex-1" disabled={busy}>
            {editing ? 'Save' : 'Add'}
          </button>
          {editing ? (
            <button type="button" className="btn" onClick={onCancelEdit} disabled={busy}>
              Cancel
            </button>
          ) : null}
        </div>
      </div>

      {derived ? (
        <p className="mt-2 text-xs font-medium" style={{ color: 'var(--color-good-text)' }}>
          {derived}
        </p>
      ) : null}

      <p className="mt-2 text-[11px] leading-relaxed text-[var(--color-muted)]">
        Give any two of amount, units and NAV — the third is worked out. Units matter for valuing
        the holding later, so record them when your statement shows them.
        {isBuy ? ' Mark a purchase as “From LenDen” when you are reinvesting P2P returns.' : ''}
      </p>

      {errors.length ? (
        <ul className="mt-2 space-y-0.5 text-xs text-[var(--color-critical)]">
          {errors.map((e) => (
            <li key={e}>• {e}</li>
          ))}
        </ul>
      ) : null}
    </form>
  );
}

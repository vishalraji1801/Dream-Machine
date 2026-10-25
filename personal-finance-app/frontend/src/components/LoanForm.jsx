import { useEffect, useState } from 'react';
import { LOAN_TYPE_META, LOAN_TYPES, todayISO } from '../lib/format.js';

const EMPTY = { date: todayISO(), type: 'drawdown', amount: '', note: '' };

const toNum = (v) => {
  if (v === '' || v === null || v === undefined) return null;
  const n = Number(String(v).replace(/[,\s₹]/g, ''));
  return Number.isFinite(n) ? n : null;
};

export default function LoanForm({ editing, onSubmit, onCancelEdit, busy, outstanding }) {
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState([]);

  useEffect(() => {
    setErrors([]);
    setForm(
      editing
        ? {
            date: editing.date,
            type: editing.type,
            amount: String(editing.amount),
            note: editing.note ?? '',
          }
        : EMPTY,
    );
  }, [editing]);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const amount = toNum(form.amount);

  // Paying back more than is owed is almost always a typo.
  const overpay =
    !editing && form.type === 'repayment' && amount !== null && typeof outstanding === 'number'
      ? amount - outstanding
      : null;

  async function handleSubmit(e) {
    e.preventDefault();

    const found = [];
    if (!form.date) found.push('Pick a date.');
    if (amount === null) found.push('Amount must be a number.');
    else if (amount <= 0) found.push('Amount must be greater than 0.');

    setErrors(found);
    if (found.length) return;

    try {
      await onSubmit({
        date: form.date,
        type: form.type,
        amount,
        note: form.note.trim() || null,
      });
      if (!editing) setForm({ ...EMPTY, date: form.date, type: form.type });
    } catch (err) {
      setErrors(err.errors ?? [err.message]);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card p-4">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold">
          {editing ? `Edit entry #${editing.id}` : 'Add loan entry'}
        </h2>
        <p className="text-xs text-[var(--color-muted)]">{LOAN_TYPE_META[form.type].hint}</p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-[repeat(4,minmax(0,1fr))_auto]">
        <div>
          <label className="label" htmlFor="ln-type">Type</label>
          <select id="ln-type" className="field" value={form.type} onChange={set('type')}>
            {LOAN_TYPES.map((t) => (
              <option key={t} value={t}>{LOAN_TYPE_META[t].label}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="label" htmlFor="ln-date">Date</label>
          <input id="ln-date" type="date" className="field" value={form.date} onChange={set('date')} />
        </div>

        <div>
          <label className="label" htmlFor="ln-amount">Amount (₹)</label>
          <input
            id="ln-amount"
            type="text"
            inputMode="decimal"
            placeholder="0.00"
            className="field"
            value={form.amount}
            onChange={set('amount')}
          />
        </div>

        <div>
          <label className="label" htmlFor="ln-note">Note (optional)</label>
          <input
            id="ln-note"
            type="text"
            placeholder="What it was for"
            className="field"
            value={form.note}
            onChange={set('note')}
          />
        </div>

        <div className="col-span-2 flex items-end gap-2 sm:col-span-4 lg:col-span-1">
          <button type="submit" className="btn btn-primary flex-1" disabled={busy}>
            {editing ? 'Save changes' : 'Add'}
          </button>
          {editing ? (
            <button type="button" className="btn" onClick={onCancelEdit} disabled={busy}>
              Cancel
            </button>
          ) : null}
        </div>
      </div>

      {overpay !== null && overpay > 0.01 ? (
        <p
          className="mt-2 rounded-md p-2 text-xs"
          style={{
            backgroundColor: 'color-mix(in srgb, var(--color-warning) 14%, transparent)',
            color: 'var(--color-ink)',
          }}
        >
          <span aria-hidden="true" className="mr-1">⚠</span>
          That is more than the ₹{outstanding.toLocaleString('en-IN')} currently outstanding. Fine if
          you are clearing the balance with a rounding, but it will push the outstanding negative.
        </p>
      ) : null}

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

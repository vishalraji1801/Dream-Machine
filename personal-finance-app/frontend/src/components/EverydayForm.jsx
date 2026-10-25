import { useEffect, useState } from 'react';
import { todayISO } from '../lib/format.js';

const EMPTY = { date: todayISO(), direction: 'out', amount: '', category: '', note: '' };

const toNum = (v) => {
  if (v === '' || v === null || v === undefined) return null;
  const n = Number(String(v).replace(/[,\s₹]/g, ''));
  return Number.isFinite(n) ? n : null;
};

export default function EverydayForm({ editing, onSubmit, onCancelEdit, busy, incomeCategories, expenseCategories }) {
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState([]);

  useEffect(() => {
    setErrors([]);
    setForm(
      editing
        ? {
            date: editing.date,
            direction: editing.direction ?? 'out',
            amount: String(editing.amount),
            category: editing.category,
            note: editing.note ?? '',
          }
        : EMPTY,
    );
  }, [editing]);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const amount = toNum(form.amount);
  const isIn = form.direction === 'in';
  const categories = isIn ? incomeCategories : expenseCategories;

  async function handleSubmit(e) {
    e.preventDefault();

    const found = [];
    if (!form.date) found.push('Pick a date.');
    if (amount === null) found.push('Amount must be a number.');
    else if (amount <= 0) found.push('Amount must be greater than 0.');
    if (!form.category.trim()) found.push('Pick or type a category.');

    setErrors(found);
    if (found.length) return;

    try {
      await onSubmit({
        date: form.date,
        direction: form.direction,
        amount,
        category: form.category.trim(),
        note: form.note.trim() || null,
      });
      if (!editing) setForm({ ...EMPTY, date: form.date, direction: form.direction });
    } catch (err) {
      setErrors(err.errors ?? [err.message]);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">
          {editing ? `Edit entry #${editing.id}` : 'Log money'}
        </h2>
        <div className="flex overflow-hidden rounded-lg border border-[var(--color-hair)]">
          {[
            { key: 'out', label: 'Money out' },
            { key: 'in', label: 'Money in' },
          ].map((d) => (
            <button
              key={d.key}
              type="button"
              onClick={() => setForm((f) => ({ ...f, direction: d.key, category: '' }))}
              aria-pressed={form.direction === d.key}
              className="px-3 py-[0.4rem] text-xs font-semibold"
              style={{
                backgroundColor:
                  form.direction === d.key
                    ? d.key === 'in'
                      ? 'color-mix(in srgb, var(--color-good) 18%, transparent)'
                      : 'var(--color-raised)'
                    : 'transparent',
                color: form.direction === d.key ? 'var(--color-ink)' : 'var(--color-muted)',
              }}
            >
              {d.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-[repeat(4,minmax(0,1fr))_auto]">
        <div>
          <label className="label" htmlFor="ed-date">Date</label>
          <input id="ed-date" type="date" className="field" value={form.date} onChange={set('date')} />
        </div>

        <div>
          <label className="label" htmlFor="ed-amount">Amount (₹)</label>
          <input
            id="ed-amount"
            type="text"
            inputMode="decimal"
            placeholder="0.00"
            className="field"
            value={form.amount}
            onChange={set('amount')}
          />
        </div>

        <div>
          <label className="label" htmlFor="ed-category">Category</label>
          <input
            id="ed-category"
            type="text"
            list="everyday-categories"
            placeholder={isIn ? 'Salary, Refund…' : 'Food, Rent…'}
            className="field"
            value={form.category}
            onChange={set('category')}
          />
          <datalist id="everyday-categories">
            {categories.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </div>

        <div>
          <label className="label" htmlFor="ed-note">Note (optional)</label>
          <input
            id="ed-note"
            type="text"
            placeholder="What was it for"
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

import { useEffect, useMemo, useState } from 'react';
import { TYPE_META, TYPES, moneyExact, todayISO } from '../lib/format.js';

const EMPTY = {
  date: todayISO(),
  type: 'deposit',
  amount: '',
  principal_portion: '',
  interest_portion: '',
};

const toNum = (v) => {
  if (v === '' || v === null || v === undefined) return null;
  const n = Number(String(v).replace(/[,\s₹]/g, ''));
  return Number.isFinite(n) ? n : null;
};

export default function TransactionForm({ editing, onSubmit, onCancelEdit, busy, idleCash }) {
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
            principal_portion:
              editing.principal_portion == null ? '' : String(editing.principal_portion),
            interest_portion:
              editing.interest_portion == null ? '' : String(editing.interest_portion),
          }
        : EMPTY,
    );
  }, [editing]);

  const isPayout = form.type === 'payout';
  const amount = toNum(form.amount);
  const principal = toNum(form.principal_portion);
  const interest = toNum(form.interest_portion);

  const split = useMemo(() => {
    if (!isPayout || amount === null) return null;
    if (principal === null && interest === null) return null;
    const sum = (principal ?? 0) + (interest ?? 0);
    return { sum, drift: sum - amount, ok: Math.abs(sum - amount) <= 0.01 };
  }, [isPayout, amount, principal, interest]);

  // Rounding a reinvestment up past the cash LenDen returned means the difference
  // came from the bank — which is a deposit, not part of the reinvestment.
  const overdraw = useMemo(() => {
    if (editing || form.type !== 'reinvest') return null;
    if (amount === null || typeof idleCash !== 'number') return null;
    const available = Math.max(idleCash, 0);
    const excess = amount - available;
    return excess > 0.01 ? { excess, available } : null;
  }, [editing, form.type, amount, idleCash]);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  function fillRemainder(field) {
    if (amount === null) return;
    const other = field === 'interest_portion' ? (principal ?? 0) : (interest ?? 0);
    const remainder = Math.round((amount - other + Number.EPSILON) * 100) / 100;
    setForm((f) => ({ ...f, [field]: String(Math.max(remainder, 0)) }));
  }

  function validate() {
    const found = [];
    if (!form.date) found.push('Pick a date.');
    if (amount === null) found.push('Amount must be a number.');
    else if (amount <= 0) found.push('Amount must be greater than 0.');

    if (isPayout) {
      if (principal === null) found.push('Principal portion is required for a payout.');
      else if (principal < 0) found.push('Principal portion cannot be negative.');
      if (interest === null) found.push('Interest portion is required for a payout.');
      else if (interest < 0) found.push('Interest portion cannot be negative.');
      if (split && !split.ok) {
        found.push(
          `Principal + interest (${moneyExact(split.sum)}) must equal the amount credited (${moneyExact(amount)}).`,
        );
      }
    }
    return found;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const found = validate();
    setErrors(found);
    if (found.length) return;

    try {
      await onSubmit({
        date: form.date,
        type: form.type,
        amount,
        principal_portion: isPayout ? principal : null,
        interest_portion: isPayout ? interest : null,
      });
      if (!editing) setForm({ ...EMPTY, date: form.date, type: form.type });
    } catch (err) {
      setErrors(err.errors ?? [err.message]);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card p-4">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold text-[var(--color-ink)]">
          {editing ? `Edit transaction #${editing.id}` : 'Add transaction'}
        </h2>
        <p className="text-xs text-[var(--color-muted)]">{TYPE_META[form.type].hint}</p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-[repeat(4,minmax(0,1fr))_auto]">
        <div>
          <label className="label" htmlFor="tx-type">Type</label>
          <select id="tx-type" className="field" value={form.type} onChange={set('type')}>
            {TYPES.map((t) => (
              <option key={t} value={t}>{TYPE_META[t].label}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="label" htmlFor="tx-date">Date</label>
          <input id="tx-date" type="date" className="field" value={form.date} onChange={set('date')} />
        </div>

        <div>
          <label className="label" htmlFor="tx-amount">
            {isPayout ? 'Amount credited (₹)' : 'Amount (₹)'}
          </label>
          <input
            id="tx-amount"
            type="text"
            inputMode="decimal"
            placeholder="0.00"
            className="field"
            value={form.amount}
            onChange={set('amount')}
          />
        </div>

        {isPayout ? (
          <>
            <div>
              <div className="flex items-baseline justify-between">
                <label className="label" htmlFor="tx-principal">Principal (₹)</label>
                <button
                  type="button"
                  onClick={() => fillRemainder('principal_portion')}
                  className="mb-1 text-[10px] font-semibold text-[var(--color-s1)] hover:underline"
                >
                  fill rest
                </button>
              </div>
              <input
                id="tx-principal"
                type="text"
                inputMode="decimal"
                placeholder="0.00"
                className="field"
                value={form.principal_portion}
                onChange={set('principal_portion')}
              />
            </div>
            <div>
              <div className="flex items-baseline justify-between">
                <label className="label" htmlFor="tx-interest">Interest (₹)</label>
                <button
                  type="button"
                  onClick={() => fillRemainder('interest_portion')}
                  className="mb-1 text-[10px] font-semibold text-[var(--color-s1)] hover:underline"
                >
                  fill rest
                </button>
              </div>
              <input
                id="tx-interest"
                type="text"
                inputMode="decimal"
                placeholder="0.00"
                className="field"
                value={form.interest_portion}
                onChange={set('interest_portion')}
              />
            </div>
          </>
        ) : null}

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

      {split ? (
        <p
          className="mt-2 text-xs font-medium"
          style={{ color: split.ok ? 'var(--color-good-text)' : 'var(--color-critical)' }}
        >
          {split.ok
            ? `Split balances: ${moneyExact(principal ?? 0)} + ${moneyExact(interest ?? 0)} = ${moneyExact(split.sum)}`
            : `Split is off by ${moneyExact(Math.abs(split.drift))} — principal + interest must equal the amount credited.`}
        </p>
      ) : null}

      {overdraw ? (
        <div
          className="mt-2 rounded-md p-2 text-xs leading-relaxed"
          style={{
            backgroundColor: 'color-mix(in srgb, var(--color-warning) 14%, transparent)',
            color: 'var(--color-ink)',
          }}
        >
          <span aria-hidden="true" className="mr-1">⚠</span>
          That is <strong>{moneyExact(overdraw.excess)}</strong> more than the{' '}
          {moneyExact(overdraw.available)} of returned cash available to reinvest. If you
          rounded up using money from your bank, record the reinvestment as{' '}
          {moneyExact(overdraw.available)} and add the extra {moneyExact(overdraw.excess)} as a
          separate <strong>deposit</strong> — otherwise it gets counted as invested twice.
          <button
            type="button"
            onClick={() => setForm((f) => ({ ...f, amount: String(overdraw.available) }))}
            className="ml-1 font-semibold text-[var(--color-s1)] hover:underline"
          >
            Use {moneyExact(overdraw.available)}
          </button>
        </div>
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

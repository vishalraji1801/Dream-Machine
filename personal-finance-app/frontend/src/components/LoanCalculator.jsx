import { useMemo, useState } from 'react';
import { money, moneyExact } from '../lib/format.js';

const toNum = (v) => {
  if (v === '' || v === null || v === undefined) return null;
  const n = Number(String(v).replace(/[,\s₹%]/g, ''));
  return Number.isFinite(n) ? n : null;
};

/**
 * Two ways to borrow against mutual funds, so the calculator covers both:
 * an overdraft where you service interest only, and a fixed EMI loan.
 */
function emiFor(principal, monthlyRate, months) {
  if (months <= 0) return 0;
  if (monthlyRate === 0) return principal / months;
  const factor = (1 + monthlyRate) ** months;
  return (principal * monthlyRate * factor) / (factor - 1);
}

export default function LoanCalculator({ defaultRate, affordablePerMonth }) {
  const [amount, setAmount] = useState('');
  const [rate, setRate] = useState(defaultRate === null || defaultRate === undefined ? '' : String(defaultRate));
  const [months, setMonths] = useState('12');
  const [mode, setMode] = useState('interest');

  const result = useMemo(() => {
    const p = toNum(amount);
    const r = toNum(rate);
    const n = toNum(months);
    if (p === null || p <= 0 || r === null || r < 0) return null;

    const monthlyRate = r / 100 / 12;
    const interestOnly = p * monthlyRate;

    if (mode === 'interest') {
      return {
        mode,
        perMonth: interestOnly,
        totalInterest: n !== null && n > 0 ? interestOnly * n : null,
        totalPayable: n !== null && n > 0 ? p + interestOnly * n : null,
        months: n,
      };
    }

    if (n === null || n <= 0) return null;
    const emi = emiFor(p, monthlyRate, n);
    return {
      mode,
      perMonth: emi,
      totalInterest: emi * n - p,
      totalPayable: emi * n,
      months: n,
    };
  }, [amount, rate, months, mode]);

  const verdict =
    result && typeof affordablePerMonth === 'number' && affordablePerMonth > 0
      ? affordablePerMonth - (mode === 'interest' ? result.perMonth : result.perMonth)
      : null;

  return (
    <section className="card p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Loan calculator</h2>
          <p className="text-xs text-[var(--color-muted)]">
            Work out what a borrowing would cost before you draw it
          </p>
        </div>
        <div className="flex overflow-hidden rounded-lg border border-[var(--color-hair)]" role="group">
          {[
            { key: 'interest', label: 'Interest only' },
            { key: 'emi', label: 'EMI' },
          ].map((m) => (
            <button
              key={m.key}
              type="button"
              onClick={() => setMode(m.key)}
              aria-pressed={mode === m.key}
              className="px-3 py-[0.4rem] text-xs font-semibold"
              style={{
                backgroundColor: mode === m.key ? 'var(--color-raised)' : 'transparent',
                color: mode === m.key ? 'var(--color-ink)' : 'var(--color-muted)',
              }}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div>
          <label className="label" htmlFor="calc-amount">Amount (₹)</label>
          <input
            id="calc-amount"
            type="text"
            inputMode="decimal"
            placeholder="100000"
            className="field"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="calc-rate">Rate (% p.a.)</label>
          <input
            id="calc-rate"
            type="text"
            inputMode="decimal"
            placeholder="10.5"
            className="field"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="calc-months">
            {mode === 'emi' ? 'Tenure (months)' : 'Hold for (months)'}
          </label>
          <input
            id="calc-months"
            type="text"
            inputMode="numeric"
            placeholder="12"
            className="field"
            value={months}
            onChange={(e) => setMonths(e.target.value)}
          />
        </div>
      </div>

      {result === null ? (
        <p className="mt-4 text-sm text-[var(--color-muted)]">
          Enter an amount and a rate{mode === 'emi' ? ' and tenure' : ''} to see the cost.
        </p>
      ) : (
        <>
          <div className="mt-4 grid gap-4 border-t border-[var(--color-line)] pt-4 sm:grid-cols-3">
            <div>
              <p className="label mb-1">{mode === 'emi' ? 'Monthly EMI' : 'Interest per month'}</p>
              <p className="text-2xl font-semibold" style={{ color: 'var(--color-critical)' }}>
                {moneyExact(result.perMonth)}
              </p>
            </div>
            <div>
              <p className="label mb-1">
                Total interest{result.months ? ` over ${result.months} mo` : ''}
              </p>
              <p className="text-2xl font-semibold">
                {result.totalInterest === null ? '—' : moneyExact(result.totalInterest)}
              </p>
            </div>
            <div>
              <p className="label mb-1">Total payable</p>
              <p className="text-2xl font-semibold">
                {result.totalPayable === null ? '—' : moneyExact(result.totalPayable)}
              </p>
            </div>
          </div>

          {verdict !== null ? (
            <p
              className="mt-3 rounded-md p-2 text-xs leading-relaxed"
              style={{
                backgroundColor:
                  verdict >= 0
                    ? 'color-mix(in srgb, var(--color-good) 12%, transparent)'
                    : 'color-mix(in srgb, var(--color-critical) 10%, transparent)',
                color: verdict >= 0 ? 'var(--color-good-text)' : 'var(--color-critical)',
              }}
            >
              {verdict >= 0
                ? `Within reach — LenDen earns about ${money(affordablePerMonth)} a month, leaving ${money(verdict)} of headroom after this.`
                : `Beyond what LenDen currently earns — that is ${money(Math.abs(verdict))} a month more than the ${money(affordablePerMonth)} coming in.`}
            </p>
          ) : null}

          <p className="mt-3 border-t border-[var(--color-line)] pt-3 text-[11px] leading-relaxed text-[var(--color-muted)]">
            {mode === 'interest'
              ? 'Interest-only: you service the interest and the principal stays outstanding until you repay it — how a credit line against mutual funds usually works.'
              : 'EMI: equal monthly instalments clear both interest and principal over the tenure, so nothing is left owing at the end.'}{' '}
            Nothing here is saved; it is a scratch calculation.
          </p>
        </>
      )}
    </section>
  );
}

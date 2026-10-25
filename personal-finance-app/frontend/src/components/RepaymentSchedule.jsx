import { useEffect, useState } from 'react';
import { api } from '../lib/api.js';
import { formatDate, money, moneyExact } from '../lib/format.js';

/**
 * Month-by-month plan at a payment you choose. The interest/principal split is the
 * point: early instalments barely dent the balance, and seeing that is what makes
 * the case for paying more.
 */
export default function RepaymentSchedule({ outstanding, suggested, rate }) {
  const [payment, setPayment] = useState('');
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    if (!(outstanding > 0)) return;
    setPayment(suggested > 0 ? String(Math.round(suggested)) : '');
  }, [outstanding, suggested]);

  useEffect(() => {
    if (!(outstanding > 0)) return;
    let cancelled = false;
    setLoading(true);
    api
      .loanSchedule(payment === '' ? undefined : payment)
      .then((p) => {
        if (!cancelled) setPlan(p);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [payment, outstanding]);

  if (!(outstanding > 0)) return null;

  const rows = plan?.rows ?? [];
  const visible = showAll ? rows : rows.slice(0, 12);

  return (
    <section className="card p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Monthly repayment plan</h2>
          <p className="text-xs text-[var(--color-muted)]">
            {money(outstanding)} at {rate}% — what each month actually does
          </p>
        </div>
        <div>
          <label className="label" htmlFor="sched-payment">Pay per month (₹)</label>
          <input
            id="sched-payment"
            className="field w-40"
            inputMode="decimal"
            value={payment}
            onChange={(e) => setPayment(e.target.value)}
          />
        </div>
      </div>

      {plan === null ? (
        <p className="py-8 text-center text-sm text-[var(--color-muted)]">
          {loading ? 'Working it out…' : 'Enter a monthly payment.'}
        </p>
      ) : !plan.viable ? (
        <div
          className="rounded-md p-3 text-sm leading-relaxed"
          style={{
            backgroundColor: 'color-mix(in srgb, var(--color-critical) 10%, transparent)',
            color: 'var(--color-critical)',
          }}
        >
          <span aria-hidden="true" className="mr-1">⚠</span>
          {plan.reason === 'below-interest' ? (
            <>
              At {moneyExact(plan.payment ?? 0)} a month this debt <strong>never clears</strong> —
              interest alone is {moneyExact(plan.interestOnly)}. You are short{' '}
              {moneyExact(plan.shortfall)} a month, so the balance would only grow. Pay more than{' '}
              {moneyExact(plan.minimumToClear)} for any of it to touch the principal.
            </>
          ) : (
            'Enter a monthly payment above the interest to see a plan.'
          )}
        </div>
      ) : (
        <>
          <div className="mb-3 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <p className="label mb-1">Clears in</p>
              <p className="text-2xl font-semibold">{plan.months} mo</p>
              <p className="mt-1 text-xs text-[var(--color-muted)]">by {formatDate(plan.clearsOn)}</p>
            </div>
            <div>
              <p className="label mb-1">Total interest</p>
              <p className="text-2xl font-semibold" style={{ color: 'var(--color-critical)' }}>
                {money(plan.totalInterest)}
              </p>
            </div>
            <div>
              <p className="label mb-1">Total paid</p>
              <p className="text-2xl font-semibold">{money(plan.totalPaid)}</p>
            </div>
            <div>
              <p className="label mb-1">First month</p>
              <p className="text-2xl font-semibold">{plan.firstMonthInterestShare}%</p>
              <p className="mt-1 text-xs text-[var(--color-muted)]">of it is interest</p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr className="border-b border-[var(--color-line)] text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
                  <th scope="col" className="px-2 py-2 text-left font-semibold">#</th>
                  <th scope="col" className="px-2 py-2 text-left font-semibold">Date</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold">Payment</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold">Interest</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold">Principal</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold">Balance left</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {visible.map((r) => (
                  <tr key={r.month} className="border-b border-[var(--color-line)] last:border-0">
                    <td className="px-2 py-1.5 text-[var(--color-muted)]">{r.month}</td>
                    <td className="px-2 py-1.5 whitespace-nowrap text-[var(--color-ink-2)]">
                      {formatDate(r.date)}
                    </td>
                    <td className="px-2 py-1.5 text-right whitespace-nowrap font-medium">
                      {moneyExact(r.payment)}
                    </td>
                    <td
                      className="px-2 py-1.5 text-right whitespace-nowrap"
                      style={{ color: 'var(--color-critical)' }}
                    >
                      {moneyExact(r.interest)}
                    </td>
                    <td
                      className="px-2 py-1.5 text-right whitespace-nowrap"
                      style={{ color: 'var(--color-good-text)' }}
                    >
                      {moneyExact(r.principal)}
                    </td>
                    <td className="px-2 py-1.5 text-right whitespace-nowrap">{moneyExact(r.balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {rows.length > 12 ? (
            <button type="button" className="btn mt-3" onClick={() => setShowAll((s) => !s)}>
              {showAll ? 'Show first 12 months' : `Show all ${rows.length} months`}
            </button>
          ) : null}

          <p className="mt-3 border-t border-[var(--color-line)] pt-3 text-[11px] leading-relaxed text-[var(--color-muted)]">
            Interest is charged on whatever is still outstanding, so it shrinks every month while
            the principal portion grows. The last instalment is only whatever is left, not the full
            amount. This assumes the rate holds and you draw nothing further.
          </p>
        </>
      )}
    </section>
  );
}

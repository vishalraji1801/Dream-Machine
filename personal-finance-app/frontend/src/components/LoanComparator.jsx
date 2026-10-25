import { useState } from 'react';
import { money, moneyExact } from '../lib/format.js';

const EMPTY = {
  lender: '',
  amount: '',
  rate: '',
  tenure_months: '12',
  processing_fee: '',
  foreclosure_pct: '',
  lock_in_months: '',
  annual_fee: '',
  other_charges: '',
  penal_rate: '',
  repayment: 'interest',
  note: '',
};

export default function LoanComparator({ comparison, onAdd, onDelete, busy, defaultRate }) {
  const [form, setForm] = useState({ ...EMPTY, rate: defaultRate ? String(defaultRate) : '' });
  const [errors, setErrors] = useState([]);
  const [open, setOpen] = useState(false);

  const offers = comparison?.offers ?? [];
  const maxRate = offers.length ? Math.max(...offers.map((o) => o.effectiveRate ?? 0)) : 0;
  const mixed =
    offers.some((o) => o.repayment === 'emi') && offers.some((o) => o.repayment === 'interest');

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setErrors([]);
    try {
      await onAdd({
        ...form,
        processing_fee: form.processing_fee === '' ? 0 : form.processing_fee,
      });
      setForm({ ...EMPTY, rate: form.rate, repayment: form.repayment });
      setOpen(false);
    } catch (err) {
      setErrors(err.errors ?? [err.message]);
    }
  }

  return (
    <section className="card p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Compare lenders</h2>
          <p className="text-xs text-[var(--color-muted)]">
            {offers.length === 0
              ? 'Add quotes to see which is genuinely cheapest'
              : `${offers.length} quote${offers.length === 1 ? '' : 's'} · ranked by true cost`}
          </p>
        </div>
        <button type="button" className="btn" onClick={() => setOpen((o) => !o)}>
          {open ? 'Cancel' : 'Add a quote'}
        </button>
      </div>

      {open ? (
        <form onSubmit={submit} className="mb-4 border-b border-[var(--color-line)] pb-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <div className="col-span-2 sm:col-span-1">
              <label className="label" htmlFor="of-lender">Lender</label>
              <input id="of-lender" className="field" placeholder="Bajaj" value={form.lender} onChange={set('lender')} />
            </div>
            <div>
              <label className="label" htmlFor="of-amount">Amount (₹)</label>
              <input id="of-amount" className="field" inputMode="decimal" placeholder="200000" value={form.amount} onChange={set('amount')} />
            </div>
            <div>
              <label className="label" htmlFor="of-rate">Rate (%)</label>
              <input id="of-rate" className="field" inputMode="decimal" placeholder="10.5" value={form.rate} onChange={set('rate')} />
            </div>
            <div>
              <label className="label" htmlFor="of-tenure">Months</label>
              <input id="of-tenure" className="field" inputMode="numeric" placeholder="24" value={form.tenure_months} onChange={set('tenure_months')} />
            </div>
            <div>
              <label className="label" htmlFor="of-fee">Fee (₹)</label>
              <input id="of-fee" className="field" inputMode="decimal" placeholder="0" value={form.processing_fee} onChange={set('processing_fee')} />
            </div>
            <div>
              <label className="label" htmlFor="of-fore">Foreclosure (%)</label>
              <input id="of-fore" className="field" inputMode="decimal" placeholder="4" value={form.foreclosure_pct} onChange={set('foreclosure_pct')} />
            </div>
            <div>
              <label className="label" htmlFor="of-lock">Lock-in (mo)</label>
              <input id="of-lock" className="field" inputMode="numeric" placeholder="6" value={form.lock_in_months} onChange={set('lock_in_months')} />
            </div>
            <div>
              <label className="label" htmlFor="of-annual">Annual fee (₹)</label>
              <input id="of-annual" className="field" inputMode="decimal" placeholder="0" value={form.annual_fee} onChange={set('annual_fee')} />
            </div>
            <div>
              <label className="label" htmlFor="of-other">Other charges (₹)</label>
              <input id="of-other" className="field" inputMode="decimal" placeholder="0" value={form.other_charges} onChange={set('other_charges')} />
            </div>
            <div>
              <label className="label" htmlFor="of-penal">Penal rate (%)</label>
              <input id="of-penal" className="field" inputMode="decimal" placeholder="24" value={form.penal_rate} onChange={set('penal_rate')} />
            </div>
            <div>
              <label className="label" htmlFor="of-repay">Repayment</label>
              <select id="of-repay" className="field" value={form.repayment} onChange={set('repayment')}>
                <option value="interest">Interest only</option>
                <option value="emi">EMI</option>
              </select>
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <button type="submit" className="btn btn-primary" disabled={busy}>Add quote</button>
          </div>
          {errors.length ? (
            <ul className="mt-2 space-y-0.5 text-xs text-[var(--color-critical)]">
              {errors.map((e) => <li key={e}>• {e}</li>)}
            </ul>
          ) : null}
        </form>
      ) : null}

      {offers.length === 0 ? (
        <p className="py-8 text-center text-sm text-[var(--color-muted)]">
          No quotes yet. Add two or more to compare them.
        </p>
      ) : (
        <>
          <ul className="mb-4 space-y-2.5">
            {[...offers].sort((a, b) => (a.effectiveRate ?? 0) - (b.effectiveRate ?? 0)).map((o) => (
              <li key={o.id}>
                <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="truncate font-medium">{o.lender}</span>
                    {o.isCheapest ? (
                      <span
                        className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase"
                        style={{ backgroundColor: 'color-mix(in srgb, var(--color-good) 18%, transparent)', color: 'var(--color-good-text)' }}
                      >
                        cheapest
                      </span>
                    ) : null}
                    <span className="shrink-0 text-[11px] text-[var(--color-muted)]">
                      {money(o.amount)} · {o.tenure_months}mo · {o.repayment === 'emi' ? 'EMI' : 'interest only'}
                    </span>
                  </span>
                  <span className="shrink-0 text-right tabular-nums">
                    <span className="font-semibold">{money(o.totalInterest)}</span>
                    <span className="ml-2 text-[11px] text-[var(--color-muted)]">interest</span>
                    <span className="block text-[11px] text-[var(--color-muted)]">
                      {o.effectiveRate}% true cost
                      {o.chargesTotal > 0 ? ` · ${money(o.chargesTotal)} charges` : ''}
                    </span>
                  </span>
                </div>
                <div className="h-2.5 w-full rounded-sm bg-[var(--color-raised)]">
                  <div
                    className="h-full"
                    style={{
                      width: `${maxRate > 0 ? Math.max(((o.effectiveRate ?? 0) / maxRate) * 100, 2) : 0}%`,
                      backgroundColor: o.isCheapest ? 'var(--color-s3)' : 'var(--color-s2)',
                      borderRadius: '2px 4px 4px 2px',
                    }}
                  />
                </div>
              </li>
            ))}
          </ul>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[960px] text-sm">
              <thead>
                <tr className="border-b border-[var(--color-line)] text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
                  <th scope="col" className="px-2 py-2 text-left font-semibold">Lender</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold">Quoted</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold" title="Annual percentage rate: the rate implied once fees are deducted from what you actually receive">APR</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold" title="Cost per rupee-year of credit actually used, including fees">True cost</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold">Per month</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold" title="Interest paid over the full tenure, excluding fees">Interest</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold" title="Processing, annual and other charges over the tenure">Charges</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold" title="Charge for clearing the loan early, and any lock-in before you may">Exit early</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold" title="Penalty rate charged on late or overdue payments">Penal</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold">Total cost</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold">Affordable?</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold"></th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {offers.map((o) => (
                  <tr key={o.id} className="border-b border-[var(--color-line)] last:border-0">
                    <td className="px-2 py-2 whitespace-nowrap font-medium">{o.lender}</td>
                    <td className="px-2 py-2 text-right text-[var(--color-ink-2)]">{o.rate}%</td>
                    <td className="px-2 py-2 text-right font-medium">
                      {o.apr === null ? '—' : o.apr + '%'}
                    </td>
                    <td
                      className="px-2 py-2 text-right font-semibold"
                      style={{ color: o.isCheapest ? 'var(--color-good-text)' : undefined }}
                    >
                      {o.effectiveRate}%
                    </td>
                    <td className="px-2 py-2 text-right whitespace-nowrap">{moneyExact(o.monthlyCost)}</td>
                    <td className="px-2 py-2 text-right whitespace-nowrap">{money(o.totalInterest)}</td>
                    <td className="px-2 py-2 text-right text-[var(--color-ink-2)]">
                      {o.chargesTotal > 0 ? money(o.chargesTotal) : '—'}
                    </td>
                    <td className="px-2 py-2 text-right text-xs text-[var(--color-ink-2)]">
                      {o.foreclosure_pct > 0 ? (
                        <>
                          {o.foreclosure_pct}% · {money(o.earlyExit.foreclosureCharge)}
                          {o.lock_in_months > 0 ? (
                            <span className="block text-[10px] text-[var(--color-muted)]">
                              {o.lock_in_months}mo lock-in
                            </span>
                          ) : null}
                        </>
                      ) : o.lock_in_months > 0 ? (
                        <span>free · {o.lock_in_months}mo lock-in</span>
                      ) : (
                        <span style={{ color: 'var(--color-good-text)' }}>free</span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-right text-xs" style={{ color: o.penal_rate > 0 ? 'var(--color-critical)' : undefined }}>
                      {o.penal_rate > 0 ? o.penal_rate + '%' : '—'}
                    </td>
                    <td className="px-2 py-2 text-right whitespace-nowrap">{money(o.totalCost)}</td>
                    <td
                      className="px-2 py-2 text-right text-xs"
                      style={{ color: o.affordable === false ? 'var(--color-critical)' : o.affordable ? 'var(--color-good-text)' : undefined }}
                    >
                      {o.affordable === null
                        ? '—'
                        : o.affordable
                          ? 'yes'
                          : `short ${money(Math.abs(o.headroom))}`}
                    </td>
                    <td className="px-2 py-2 text-right">
                      <button type="button" className="btn btn-danger px-2 py-1" onClick={() => onDelete(o)}>
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="mt-3 border-t border-[var(--color-line)] pt-3 text-[11px] leading-relaxed text-[var(--color-muted)]">
            <strong>APR</strong> is the rate implied once fees come off what you actually receive — a
            fee-free quote shows its headline rate, anything else shows higher. <strong>True cost</strong>
            additionally measures against the credit you really have use of, so EMI and interest-only
            quotes stay comparable. <strong>Penal</strong> is what applies if you pay late; it is not in
            the cost figures, since it only bites if you miss a payment.
            {mixed
              ? ' You are comparing EMI against interest-only quotes: an EMI loan repays principal as it goes, so you hold less money — this figure already corrects for that, which plain total cost would not.'
              : ''}{' '}
            Affordability is measured against what LenDen currently earns each month
            {comparison.affordablePerMonth ? ` (${money(comparison.affordablePerMonth)})` : ''}.
          </p>
        </>
      )}
    </section>
  );
}

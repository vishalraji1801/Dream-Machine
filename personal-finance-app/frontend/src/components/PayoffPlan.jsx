import { money, moneyExact } from '../lib/format.js';

/**
 * The speed/cost trade-off: clearing faster costs more each month but less overall.
 * Shown as a table rather than a single "optimal" number, because which row is best
 * depends on what you can actually afford — there is no one right answer.
 */
export default function PayoffPlan({ payoff, title, subtitle, affordablePerMonth }) {
  if (!payoff) return null;

  const { rows, interestOnly, principal, rate } = payoff;
  const maxInterest = Math.max(...rows.map((r) => r.totalInterest));

  // The quickest option you could actually service, if we know what you can afford.
  const best =
    typeof affordablePerMonth === 'number' && affordablePerMonth > 0
      ? rows.filter((r) => r.payment <= affordablePerMonth).sort((a, b) => a.months - b.months)[0] ?? null
      : null;

  return (
    <section className="card p-4">
      <div className="mb-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="text-xs text-[var(--color-muted)]">
          {subtitle ?? `${money(principal)} at ${rate}% — pay faster, pay less in total`}
        </p>
      </div>

      <div
        className="mb-3 rounded-md p-2 text-xs leading-relaxed"
        style={{
          backgroundColor: 'color-mix(in srgb, var(--color-warning) 14%, transparent)',
          color: 'var(--color-ink)',
        }}
      >
        <span aria-hidden="true" className="mr-1">⚠</span>
        Paying only the interest — <strong>{moneyExact(interestOnly.payment)}</strong> a month,{' '}
        {money(interestOnly.costPerYear)} a year — never reduces the balance. The debt stays at{' '}
        {money(principal)} indefinitely.
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="border-b border-[var(--color-line)] text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
              <th scope="col" className="px-2 py-2 text-left font-semibold">Clear in</th>
              <th scope="col" className="px-2 py-2 text-right font-semibold">Per month</th>
              <th scope="col" className="px-2 py-2 text-right font-semibold">Total interest</th>
              <th scope="col" className="px-2 py-2 text-left font-semibold">Relative cost</th>
              <th scope="col" className="px-2 py-2 text-right font-semibold">Saved</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((r) => {
              const isBest = best !== null && r.months === best.months;
              const unaffordable =
                typeof affordablePerMonth === 'number' &&
                affordablePerMonth > 0 &&
                r.payment > affordablePerMonth;

              return (
                <tr
                  key={r.months}
                  className="border-b border-[var(--color-line)] last:border-0"
                  style={{ opacity: unaffordable ? 0.5 : 1 }}
                >
                  <td className="px-2 py-2 whitespace-nowrap font-medium">
                    {r.months} mo
                    {isBest ? (
                      <span
                        className="ml-2 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase"
                        style={{
                          backgroundColor: 'color-mix(in srgb, var(--color-good) 18%, transparent)',
                          color: 'var(--color-good-text)',
                        }}
                      >
                        best you can service
                      </span>
                    ) : null}
                  </td>
                  <td className="px-2 py-2 text-right whitespace-nowrap font-semibold">
                    {moneyExact(r.payment)}
                  </td>
                  <td className="px-2 py-2 text-right whitespace-nowrap">{money(r.totalInterest)}</td>
                  <td className="px-2 py-2">
                    <div className="h-2 w-full min-w-[80px] rounded-sm bg-[var(--color-raised)]">
                      <div
                        className="h-full"
                        style={{
                          width: `${maxInterest > 0 ? Math.max((r.totalInterest / maxInterest) * 100, 2) : 0}%`,
                          backgroundColor: 'var(--color-s2)',
                          borderRadius: '2px 4px 4px 2px',
                        }}
                      />
                    </div>
                  </td>
                  <td
                    className="px-2 py-2 text-right whitespace-nowrap"
                    style={{ color: r.savedVsSlowest > 0 ? 'var(--color-good-text)' : undefined }}
                  >
                    {r.savedVsSlowest > 0 ? `${money(r.savedVsSlowest)}` : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-3 border-t border-[var(--color-line)] pt-3 text-[11px] leading-relaxed text-[var(--color-muted)]">
        Saved is measured against the slowest option ({payoff.baselineMonths} months). There is no
        single optimal row — the fastest schedule always costs least in total, so the real question
        is the largest instalment you can comfortably sustain.
        {typeof affordablePerMonth === 'number' && affordablePerMonth > 0
          ? ` Rows above ${money(affordablePerMonth)} a month are dimmed, since that is what LenDen currently earns you.`
          : ''}
      </p>
    </section>
  );
}

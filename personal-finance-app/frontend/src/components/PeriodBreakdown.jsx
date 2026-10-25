import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { compactMoney, money, moneyExact } from '../lib/format.js';
import { useChartTheme } from '../lib/useChartTheme.js';

const GRAINS = [
  { key: 'day', label: 'Day' },
  { key: 'week', label: 'Week' },
  { key: 'month', label: 'Month' },
  { key: 'year', label: 'Year' },
];

const GRAIN_NOUN = { day: 'day', week: 'week', month: 'month', year: 'year' };

function fmt(iso, opts) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-IN', { timeZone: 'UTC', ...opts });
}

export function periodLabel(period) {
  const { grain, start, end, key } = period;
  if (grain === 'year') return key;
  if (grain === 'month') return fmt(start, { month: 'short', year: 'numeric' });
  if (grain === 'day') return fmt(start, { day: '2-digit', month: 'short' });

  const sameMonth = start.slice(0, 7) === end.slice(0, 7);
  const from = fmt(start, sameMonth ? { day: '2-digit' } : { day: '2-digit', month: 'short' });
  return `${from}–${fmt(end, { day: '2-digit', month: 'short' })}`;
}

function PeriodTooltip({ active, payload, colors }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;

  const rows = [
    ['Interest earned', money(p.interest)],
    ['Payouts received', String(p.payoutCount)],
    ['Money in', money(p.deposited)],
    ['Money out', money(p.withdrawn)],
    ['Value at close', money(p.closingValue)],
  ];

  return (
    <div
      className="rounded-lg px-3 py-2 text-xs shadow-lg"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.hair}`, color: colors.ink }}
    >
      <p className="mb-1.5 font-semibold">{p.label}</p>
      <dl className="space-y-1 tabular-nums">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-5">
            <dt style={{ color: colors['ink-2'] }}>{k}</dt>
            <dd className="font-medium">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export default function PeriodBreakdown({ data, grain, onGrainChange, themeKey }) {
  const colors = useChartTheme(themeKey);
  const periods = (data?.periods ?? []).map((p) => ({ ...p, label: periodLabel(p) }));
  const noun = GRAIN_NOUN[grain] ?? 'period';

  return (
    <section className="card p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Earnings by period</h2>
          <p className="text-xs text-[var(--color-muted)]">
            Interest received per {noun}, with money in and out
          </p>
        </div>

        <div
          className="flex overflow-hidden rounded-lg border border-[var(--color-hair)]"
          role="group"
          aria-label="Group by"
        >
          {GRAINS.map((g) => (
            <button
              key={g.key}
              type="button"
              onClick={() => onGrainChange(g.key)}
              aria-pressed={grain === g.key}
              className="px-3 py-[0.4rem] text-xs font-semibold"
              style={{
                backgroundColor: grain === g.key ? 'var(--color-raised)' : 'transparent',
                color: grain === g.key ? 'var(--color-ink)' : 'var(--color-muted)',
              }}
            >
              {g.label}
            </button>
          ))}
        </div>
      </div>

      {periods.length === 0 ? (
        <p className="py-10 text-center text-sm text-[var(--color-muted)]">
          No activity logged yet.
        </p>
      ) : (
        <>
          <dl className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-xs">
            <div className="flex items-baseline gap-1.5">
              <dt className="text-[var(--color-muted)]">Total interest</dt>
              <dd className="font-semibold tabular-nums">{money(data.totals.interest)}</dd>
            </div>
            <div className="flex items-baseline gap-1.5">
              <dt className="text-[var(--color-muted)]">Average per earning {noun}</dt>
              <dd className="font-semibold tabular-nums">{money(data.averageInterest)}</dd>
            </div>
            {data.best ? (
              <div className="flex items-baseline gap-1.5">
                <dt className="text-[var(--color-muted)]">Best</dt>
                <dd className="font-semibold tabular-nums">
                  {periodLabel({ ...data.best, grain })} · {money(data.best.interest)}
                </dd>
              </div>
            ) : null}
          </dl>

          <div className="h-52 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={periods} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={colors.grid} vertical={false} />
                <XAxis
                  dataKey="label"
                  tick={{ fill: colors.muted, fontSize: 11 }}
                  axisLine={{ stroke: colors.hair }}
                  tickLine={false}
                  minTickGap={8}
                />
                <YAxis
                  tickFormatter={compactMoney}
                  tick={{ fill: colors.muted, fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                  width={56}
                />
                <Tooltip
                  content={<PeriodTooltip colors={colors} />}
                  cursor={{ fill: colors.grid, fillOpacity: 0.4 }}
                />
                <Bar
                  dataKey="interest"
                  fill={colors.s1}
                  maxBarSize={24}
                  radius={[4, 4, 0, 0]}
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr className="border-b border-[var(--color-line)] text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
                  <th scope="col" className="px-2 py-2 text-left font-semibold">Period</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold">Interest</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold" title="Interest as a percentage of the capital working during the period">Return</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold" title="That period return scaled to a yearly rate">Annualised</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold">Payouts</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold">In</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold">Out</th>
                  <th scope="col" className="px-2 py-2 text-right font-semibold">Value at close</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {[...periods].reverse().map((p) => (
                  <tr key={p.key} className="border-b border-[var(--color-line)] last:border-0">
                    <td className="px-2 py-2 whitespace-nowrap font-medium">{p.label}</td>
                    <td
                      className="px-2 py-2 text-right whitespace-nowrap font-semibold"
                      style={{ color: p.interest > 0 ? 'var(--color-good-text)' : undefined }}
                    >
                      {p.interest > 0 ? moneyExact(p.interest) : '—'}
                    </td>
                    <td
                      className="px-2 py-2 text-right whitespace-nowrap font-semibold"
                      style={{ color: p.returnPct > 0 ? 'var(--color-good-text)' : undefined }}
                    >
                      {p.returnPct === null ? '—' : p.returnPct.toFixed(2) + '%'}
                    </td>
                    <td className="px-2 py-2 text-right whitespace-nowrap text-[var(--color-ink-2)]">
                      {p.annualisedPct === null ? '—' : p.annualisedPct.toFixed(1) + '%'}
                    </td>
                    <td className="px-2 py-2 text-right text-[var(--color-ink-2)]">
                      {p.payoutCount || '—'}
                    </td>
                    <td className="px-2 py-2 text-right whitespace-nowrap text-[var(--color-ink-2)]">
                      {p.deposited > 0 ? moneyExact(p.deposited) : '—'}
                    </td>
                    <td className="px-2 py-2 text-right whitespace-nowrap text-[var(--color-ink-2)]">
                      {p.withdrawn > 0 ? moneyExact(p.withdrawn) : '—'}
                    </td>
                    <td className="px-2 py-2 text-right whitespace-nowrap">
                      {moneyExact(p.closingValue)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="mt-2 text-[11px] text-[var(--color-muted)]">
            Only periods with activity are listed. Reinvestments are excluded — they move money
            within LenDen rather than in or out.
          </p>
        </>
      )}
    </section>
  );
}

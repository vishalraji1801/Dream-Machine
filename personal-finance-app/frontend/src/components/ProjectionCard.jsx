import { useState } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { compactMoney, formatDate, money } from '../lib/format.js';
import { useChartTheme } from '../lib/useChartTheme.js';

const BASE_SERIES = [
  { key: 'actual', name: 'Actual so far', token: 's3' },
  { key: 'value', name: 'Projected', token: 's1' },
  { key: 'contributed', name: 'Your money in', token: 's2' },
];
const LOAN_SERIES = { key: 'netValue', name: 'After clearing the loan', token: 'critical' };

/** The net-of-loan line only exists once a loan is actually drawn. */
function seriesFor(point, hasLoan) {
  const showLoan = point ? typeof point.netValue === 'number' : hasLoan;
  return showLoan ? [...BASE_SERIES, LOAN_SERIES] : BASE_SERIES;
}

function ProjTooltip({ active, payload, colors }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;

  // History points carry no month index; forecast points do.
  const heading =
    p.month === null || p.month === undefined
      ? formatDate(p.date)
      : p.month === 0
        ? `Today · ${formatDate(p.date)}`
        : `${formatDate(p.date)} · ${p.month} month${p.month === 1 ? '' : 's'} out`;

  const shown = seriesFor(p).filter((s) => typeof p[s.key] === 'number');

  return (
    <div
      className="rounded-lg px-3 py-2 text-xs shadow-lg"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.hair}`, color: colors.ink }}
    >
      <p className="mb-1.5 font-semibold">{heading}</p>
      <dl className="space-y-1 tabular-nums">
        {shown.map((s) => (
          <div key={s.key} className="flex items-center justify-between gap-4">
            <dt className="flex items-center gap-1.5" style={{ color: colors['ink-2'] }}>
              <span
                aria-hidden="true"
                style={{ display: 'inline-block', width: 10, height: 2, borderRadius: 1, backgroundColor: colors[s.token] }}
              />
              {s.name}
            </dt>
            <dd className="font-medium">{money(p[s.key])}</dd>
          </div>
        ))}
        {typeof p.interest === 'number' ? (
          <div
            className="flex items-center justify-between gap-4 border-t pt-1"
            style={{ borderColor: colors.hair, color: colors['ink-2'] }}
          >
            <dt>Interest earned</dt>
            <dd className="font-medium" style={{ color: colors.ink }}>{money(p.interest)}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}

export default function ProjectionCard({ data, onChange, themeKey, busy }) {
  const colors = useChartTheme(themeKey);
  const [open, setOpen] = useState(false);

  if (!data) return null;
  const { basis, assumptions, projected, milestones, series, loan } = data;
  const thin = basis.monthsObserved < 3;
  const hasLoan = Boolean(loan);

  const update = (patch) => onChange({ ...assumptions, ...patch });

  return (
    <section className="card p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Where this could go</h2>
          <p className="text-xs text-[var(--color-muted)]">
            {assumptions.usingDefaults
              ? `Projected from your own history — ${basis.observedYield ?? 0}% observed yield`
              : 'Projected from your assumptions'}
          </p>
        </div>
        <button type="button" className="btn" onClick={() => setOpen((o) => !o)}>
          {open ? 'Hide assumptions' : 'Adjust assumptions'}
        </button>
      </div>

      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <div>
          <p className="label mb-1">In {assumptions.months} months</p>
          <p className="text-4xl font-semibold tracking-tight">{money(projected.value)}</p>
          <p className="mt-1 text-sm text-[var(--color-ink-2)]">
            from {money(basis.currentValue)} ·{' '}
            <span style={{ color: 'var(--color-good-text)' }}>+{money(projected.growth)}</span>
          </p>
          <p className="mt-1 text-xs text-[var(--color-muted)]">
            {money(projected.interest)} of that is interest
          </p>

          {hasLoan ? (
            <dl className="mt-3 space-y-1 border-t border-[var(--color-line)] pt-3 text-xs">
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-[var(--color-muted)]">Loan interest over this horizon</dt>
                <dd className="font-semibold tabular-nums" style={{ color: 'var(--color-critical)' }}>
                  −{money(loan.interestOverHorizon)}
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-[var(--color-muted)]">Owed at the end</dt>
                <dd className="font-semibold tabular-nums">{money(loan.owedAtEnd)}</dd>
              </div>
              <div className="flex items-baseline justify-between gap-3 border-t border-[var(--color-line)] pt-1">
                <dt className="font-semibold">After clearing the loan</dt>
                <dd
                  className="font-semibold tabular-nums"
                  style={{ color: loan.worthIt ? 'var(--color-good-text)' : 'var(--color-critical)' }}
                >
                  {money(loan.netValue)}
                </dd>
              </div>
            </dl>
          ) : null}

          {milestones.length > 1 ? (
            <dl className="mt-3 space-y-1 border-t border-[var(--color-line)] pt-3 text-xs">
              {milestones.map((m) => (
                <div key={m.month} className="flex items-baseline justify-between gap-3">
                  <dt className="text-[var(--color-muted)]">
                    {m.month % 12 === 0 ? `${m.month / 12} year${m.month === 12 ? '' : 's'}` : `${m.month} months`}
                  </dt>
                  <dd className="font-semibold tabular-nums">{money(m.value)}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>

        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={series} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="projWash" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={colors.s1} stopOpacity={0.16} />
                  <stop offset="100%" stopColor={colors.s1} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={colors.grid} vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={(d) => formatDate(d).replace(/ \d{4}$/, '')}
                tick={{ fill: colors.muted, fontSize: 11 }}
                axisLine={{ stroke: colors.hair }}
                tickLine={false}
                minTickGap={24}
              />
              <YAxis
                tickFormatter={compactMoney}
                tick={{ fill: colors.muted, fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={56}
              />
              <Tooltip content={<ProjTooltip colors={colors} />} cursor={{ stroke: colors.hair }} />
              <Area type="monotone" dataKey="value" stroke="none" fill="url(#projWash)" isAnimationActive={false} />
              <Line
                type="monotone"
                dataKey="actual"
                stroke={colors.s3}
                strokeWidth={2}
                dot={false}
                connectNulls
                activeDot={{ r: 4, strokeWidth: 2, stroke: colors.surface }}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="contributed"
                stroke={colors.s2}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: colors.surface }}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke={colors.s1}
                strokeWidth={2}
                strokeDasharray="5 4"
                dot={false}
                connectNulls
                activeDot={{ r: 4, strokeWidth: 2, stroke: colors.surface }}
                isAnimationActive={false}
              />
              {hasLoan ? (
                <Line
                  type="monotone"
                  dataKey="netValue"
                  stroke={colors.critical}
                  strokeWidth={2}
                  strokeDasharray="5 4"
                  dot={false}
                  connectNulls
                  activeDot={{ r: 4, strokeWidth: 2, stroke: colors.surface }}
                  isAnimationActive={false}
                />
              ) : null}
            </ComposedChart>
          </ResponsiveContainer>
          <ul className="mt-1 flex flex-wrap gap-4 text-xs text-[var(--color-ink-2)]">
            {seriesFor(null, hasLoan).map((s) => (
              <li key={s.key} className="flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="inline-block h-0.5 w-4 rounded-full"
                  style={{ backgroundColor: `var(--color-${s.token})` }}
                />
                {s.name}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {open ? (
        <div className="mt-4 grid gap-4 border-t border-[var(--color-line)] pt-4 sm:grid-cols-3">
          <div>
            <label className="label" htmlFor="pj-yield">
              Expected yield — {assumptions.yieldPct}% p.a.
            </label>
            <input
              id="pj-yield"
              type="range"
              min="0"
              max="30"
              step="0.5"
              className="w-full"
              value={assumptions.yieldPct}
              disabled={busy}
              onChange={(e) => update({ yieldPct: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="label" htmlFor="pj-topup">
              Monthly top-up — {money(assumptions.monthlyTopUp)}
            </label>
            <input
              id="pj-topup"
              type="range"
              min="0"
              max="50000"
              step="500"
              className="w-full"
              value={assumptions.monthlyTopUp}
              disabled={busy}
              onChange={(e) => update({ monthlyTopUp: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="label" htmlFor="pj-months">
              Horizon — {assumptions.months} months
            </label>
            <input
              id="pj-months"
              type="range"
              min="3"
              max="120"
              step="3"
              className="w-full"
              value={assumptions.months}
              disabled={busy}
              onChange={(e) => update({ months: Number(e.target.value) })}
            />
          </div>
          <div className="sm:col-span-3">
            <button
              type="button"
              className="btn"
              onClick={() => onChange(null)}
              disabled={busy || assumptions.usingDefaults}
            >
              Reset to my actual history
            </button>
          </div>
        </div>
      ) : null}

      <p className="mt-3 border-t border-[var(--color-line)] pt-3 text-[11px] leading-relaxed text-[var(--color-muted)]">
        {thin
          ? `This is a projection, not a forecast — and the ${basis.observedYield ?? 0}% yield behind it comes from only ${basis.monthsObserved} earning ${basis.monthsObserved === 1 ? 'month' : 'months'}, which is far too little to extrapolate from. `
          : 'This is a projection, not a forecast. '}
        Interest compounds monthly — each month it is added to the balance and earns in its turn. The dashed line is the forecast; the solid green line is what actually happened. Real P2P
        returns vary, borrowers default, and nothing here accounts for loans going bad — your
        non-performing total is already deducted from the starting value, but future defaults are not.
      </p>
    </section>
  );
}

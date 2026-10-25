import {
  Area,
  CartesianGrid,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { compactMoney, money, moneyExact } from '../lib/format.js';
import { useChartTheme } from '../lib/useChartTheme.js';

export function monthLabel(month) {
  if (!month) return '';
  const [y, m] = month.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString('en-IN', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

function shiftMonth(month, delta) {
  const [y, m] = month.split('-').map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

function CategoryBars({ rows }) {
  if (rows.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-[var(--color-muted)]">
        Nothing logged this month yet.
      </p>
    );
  }

  const max = Math.max(...rows.map((r) => r.amount));

  return (
    <ul className="space-y-2.5">
      {rows.map((row) => (
        <li key={row.category}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
            <span className="flex min-w-0 items-center gap-2">
              <span className="truncate font-medium">{row.category}</span>
              {row.derived ? (
                <span className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--color-ink-2)] bg-[var(--color-raised)]">
                  from portfolio
                </span>
              ) : null}
            </span>
            <span className="shrink-0 tabular-nums">
              <span className="font-semibold">{money(row.amount)}</span>
              <span className="ml-2 text-[11px] text-[var(--color-muted)]">
                {(row.share * 100).toFixed(1)}%
              </span>
            </span>
          </div>
          <div className="h-2.5 w-full rounded-sm bg-[var(--color-raised)]">
            <div
              className="h-full"
              style={{
                width: `${Math.max((row.amount / max) * 100, 1.5)}%`,
                backgroundColor: row.derived ? 'var(--color-s2)' : 'var(--color-s1)',
                borderRadius: '2px 4px 4px 2px',
              }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

function PaceTooltip({ active, payload, colors }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div
      className="rounded-lg px-3 py-2 text-xs shadow-lg"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.hair}`, color: colors.ink }}
    >
      <p className="mb-1 font-semibold">Day {p.day}</p>
      <p className="tabular-nums" style={{ color: colors['ink-2'] }}>
        Spent that day <span style={{ color: colors.ink }}>{money(p.spent)}</span>
      </p>
      <p className="tabular-nums" style={{ color: colors['ink-2'] }}>
        Running total <span style={{ color: colors.ink }}>{money(p.cumulative)}</span>
      </p>
    </div>
  );
}

function SpendPace({ data, themeKey }) {
  const colors = useChartTheme(themeKey);
  if (!data || data.length === 0) return null;

  return (
    <div className="h-40 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="spendWash" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={colors.s1} stopOpacity={0.18} />
              <stop offset="100%" stopColor={colors.s1} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={colors.grid} vertical={false} />
          <XAxis
            dataKey="day"
            tick={{ fill: colors.muted, fontSize: 10 }}
            axisLine={{ stroke: colors.hair }}
            tickLine={false}
            minTickGap={20}
          />
          <YAxis
            tickFormatter={compactMoney}
            tick={{ fill: colors.muted, fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={48}
          />
          <Tooltip content={<PaceTooltip colors={colors} />} cursor={{ stroke: colors.hair }} />
          <Area
            type="monotone"
            dataKey="cumulative"
            stroke={colors.s1}
            strokeWidth={2}
            fill="url(#spendWash)"
            isAnimationActive={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: colors.surface }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function SpendingView({ summary, onMonthChange, themeKey }) {
  const { month, spent, invested, totalOut, byCategory, dailyTotals, months } = summary;
  const label = monthLabel(month);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1">
          <button type="button" className="btn px-2 py-1" onClick={() => onMonthChange(shiftMonth(month, -1))}>
            ◀
          </button>
          <label className="sr-only" htmlFor="month-pick">Month</label>
          <select
            id="month-pick"
            className="field w-auto font-semibold"
            value={month}
            onChange={(e) => onMonthChange(e.target.value)}
          >
            {(months.includes(month) ? months : [month, ...months]).map((m) => (
              <option key={m} value={m}>{monthLabel(m)}</option>
            ))}
          </select>
          <button type="button" className="btn px-2 py-1" onClick={() => onMonthChange(shiftMonth(month, 1))}>
            ▶
          </button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <div className="card flex flex-col justify-center p-5">
          <p className="label mb-1">Total out — {label}</p>
          <p className="text-5xl font-semibold tracking-tight">{money(totalOut)}</p>
          <dl className="mt-3 space-y-1 text-sm">
            <div className="flex items-center justify-between gap-3">
              <dt className="flex items-center gap-2 text-[var(--color-ink-2)]">
                <span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm bg-[var(--color-s1)]" />
                Spent
              </dt>
              <dd className="font-semibold tabular-nums">{moneyExact(spent)}</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="flex items-center gap-2 text-[var(--color-ink-2)]">
                <span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm bg-[var(--color-s2)]" />
                Invested in LenDen
              </dt>
              <dd className="font-semibold tabular-nums">{moneyExact(invested)}</dd>
            </div>
          </dl>
          <p className="mt-2 text-xs text-[var(--color-muted)]">
            Invested is pulled from your portfolio deposits — you never type it twice.
          </p>
        </div>

        <section className="card p-4">
          <div className="mb-3">
            <h2 className="text-sm font-semibold">Where it went</h2>
            <p className="text-xs text-[var(--color-muted)]">Ranked by amount, share of total out</p>
          </div>
          <CategoryBars rows={byCategory} />
        </section>
      </div>

      {dailyTotals.length > 0 ? (
        <section className="card p-4">
          <div className="mb-2">
            <h2 className="text-sm font-semibold">Spending pace</h2>
            <p className="text-xs text-[var(--color-muted)]">
              Running total through {label} (logged expenses only)
            </p>
          </div>
          <SpendPace data={dailyTotals} themeKey={themeKey} />
        </section>
      ) : null}
    </div>
  );
}

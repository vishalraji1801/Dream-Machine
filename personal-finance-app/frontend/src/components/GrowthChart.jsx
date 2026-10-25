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

const SERIES = [
  { key: 'value', name: 'Portfolio value', token: 's1' },
  { key: 'deposited', name: 'Net deposited', token: 's2' },
];

function ChartTooltip({ active, payload, label, colors }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;

  return (
    <div
      className="rounded-lg px-3 py-2 text-xs shadow-lg"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.hair}`,
        color: colors.ink,
      }}
    >
      <p className="mb-1.5 font-semibold">{formatDate(label)}</p>
      <dl className="space-y-1 tabular-nums">
        {SERIES.map((s) => (
          <div key={s.key} className="flex items-center justify-between gap-4">
            <dt className="flex items-center gap-1.5" style={{ color: colors['ink-2'] }}>
              <span
                aria-hidden="true"
                style={{
                  display: 'inline-block',
                  width: 10,
                  height: 2,
                  borderRadius: 1,
                  backgroundColor: colors[s.token],
                }}
              />
              {s.name}
            </dt>
            <dd className="font-medium">{money(point[s.key])}</dd>
          </div>
        ))}
        <div
          className="flex items-center justify-between gap-4 border-t pt-1"
          style={{ borderColor: colors.hair, color: colors['ink-2'] }}
        >
          <dt>Interest earned</dt>
          <dd className="font-medium" style={{ color: colors.ink }}>{money(point.interest)}</dd>
        </div>
        <div className="flex items-center justify-between gap-4" style={{ color: colors['ink-2'] }}>
          <dt>Withdrawn</dt>
          <dd className="font-medium" style={{ color: colors.ink }}>{money(point.withdrawn)}</dd>
        </div>
      </dl>
    </div>
  );
}

export default function GrowthChart({ data, themeKey }) {
  const colors = useChartTheme(themeKey);

  if (!data || data.length < 2) {
    return (
      <div className="flex h-72 items-center justify-center text-sm text-[var(--color-muted)]">
        Add at least two dated transactions to plot growth.
      </div>
    );
  }

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 4 }}>
          <defs>
            <linearGradient id="valueWash" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={colors.s1} stopOpacity={0.16} />
              <stop offset="100%" stopColor={colors.s1} stopOpacity={0.02} />
            </linearGradient>
          </defs>

          <CartesianGrid stroke={colors.grid} strokeWidth={1} vertical={false} />

          <XAxis
            dataKey="date"
            tickFormatter={(d) => formatDate(d).replace(/ \d{4}$/, '')}
            tick={{ fill: colors.muted, fontSize: 11 }}
            axisLine={{ stroke: colors.hair }}
            tickLine={false}
            minTickGap={28}
          />
          <YAxis
            tickFormatter={compactMoney}
            tick={{ fill: colors.muted, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={56}
          />
          <Tooltip
            content={<ChartTooltip colors={colors} />}
            cursor={{ stroke: colors.hair, strokeWidth: 1 }}
          />

          <Area
            type="monotone"
            dataKey="value"
            stroke="none"
            fill="url(#valueWash)"
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="deposited"
            stroke={colors.s2}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: colors.surface }}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={colors.s1}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: colors.surface }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function GrowthLegend() {
  return (
    <ul className="flex flex-wrap items-center gap-4 text-xs text-[var(--color-ink-2)]">
      {SERIES.map((s) => (
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
  );
}

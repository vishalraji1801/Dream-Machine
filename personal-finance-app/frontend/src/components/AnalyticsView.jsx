import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { formatDate } from '../lib/format.js';
import { useChartTheme } from '../lib/useChartTheme.js';

function Tile({ label, value, note }) {
  return (
    <div className="card p-4">
      <p className="label mb-1">{label}</p>
      <p className="text-2xl font-semibold">{value}</p>
      {note ? <p className="mt-1 text-xs text-[var(--color-muted)]">{note}</p> : null}
    </div>
  );
}

function relative(ts) {
  if (!ts) return 'never';
  const then = new Date(`${ts.replace(' ', 'T')}Z`);
  const days = Math.floor((Date.now() - then.getTime()) / 86400000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days} days ago`;
  return formatDate(ts.slice(0, 10));
}

export default function AnalyticsView({ data, onClear, busy, themeKey }) {
  const colors = useChartTheme(themeKey);
  if (!data) return null;

  const used = data.features.filter((f) => f.used);
  const maxCount = used.length ? Math.max(...used.map((f) => f.count)) : 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Tile label="Actions recorded" value={data.total} note={`Since ${relative(data.trackingSince)}`} />
        <Tile
          label="Features used"
          value={`${data.usedCount} of ${data.featureCount}`}
          note={`${data.unused.length} never touched`}
        />
        <Tile
          label="Busiest tab"
          value={data.tabViews[0]?.tab ?? '—'}
          note={data.tabViews[0] ? `${data.tabViews[0].count} visits` : 'No tab views yet'}
        />
        <Tile
          label="Last 30 days"
          value={data.daily.reduce((s, d) => s + d.count, 0)}
          note="Actions in the window"
        />
      </div>

      {data.daily.length > 1 ? (
        <section className="card p-4">
          <div className="mb-3">
            <h2 className="text-sm font-semibold">Activity over time</h2>
            <p className="text-xs text-[var(--color-muted)]">Actions per day, last {data.days} days</p>
          </div>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.daily} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={colors.grid} vertical={false} />
                <XAxis
                  dataKey="date"
                  tickFormatter={(d) => formatDate(d).replace(/ \d{4}$/, '')}
                  tick={{ fill: colors.muted, fontSize: 11 }}
                  axisLine={{ stroke: colors.hair }}
                  tickLine={false}
                  minTickGap={20}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fill: colors.muted, fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                  width={32}
                />
                <Tooltip
                  cursor={{ fill: colors.grid, fillOpacity: 0.4 }}
                  content={({ active, payload, label }) =>
                    active && payload?.length ? (
                      <div
                        className="rounded-lg px-3 py-2 text-xs shadow-lg"
                        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.hair}`, color: colors.ink }}
                      >
                        <p className="font-semibold">{formatDate(label)}</p>
                        <p style={{ color: colors['ink-2'] }}>{payload[0].value} actions</p>
                      </div>
                    ) : null
                  }
                />
                <Bar dataKey="count" fill={colors.s1} maxBarSize={24} radius={[4, 4, 0, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card p-4">
          <div className="mb-3">
            <h2 className="text-sm font-semibold">What you use</h2>
            <p className="text-xs text-[var(--color-muted)]">Ranked by how often</p>
          </div>
          {used.length === 0 ? (
            <p className="py-8 text-center text-sm text-[var(--color-muted)]">Nothing recorded yet.</p>
          ) : (
            <ul className="space-y-2.5">
              {used.map((f) => (
                <li key={f.key}>
                  <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="truncate font-medium">{f.label}</span>
                      <span className="shrink-0 text-[11px] text-[var(--color-muted)]">{f.tab}</span>
                    </span>
                    <span className="shrink-0 tabular-nums">
                      <span className="font-semibold">{f.count}</span>
                      <span className="ml-2 text-[11px] text-[var(--color-muted)]">{relative(f.lastUsed)}</span>
                    </span>
                  </div>
                  <div className="h-2 w-full rounded-sm bg-[var(--color-raised)]">
                    <div
                      className="h-full"
                      style={{
                        width: `${maxCount > 0 ? Math.max((f.count / maxCount) * 100, 2) : 0}%`,
                        backgroundColor: 'var(--color-s1)',
                        borderRadius: '2px 4px 4px 2px',
                      }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card p-4">
          <div className="mb-3">
            <h2 className="text-sm font-semibold">What you don't</h2>
            <p className="text-xs text-[var(--color-muted)]">
              {data.unused.length === 0 ? 'You have used everything' : 'Never touched so far'}
            </p>
          </div>
          {data.unused.length === 0 ? (
            <p className="py-8 text-center text-sm" style={{ color: 'var(--color-good-text)' }}>
              Every feature has been used at least once.
            </p>
          ) : (
            <ul className="space-y-2">
              {data.unused.map((f) => (
                <li key={f.key} className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="flex min-w-0 items-center gap-2">
                    <span
                      aria-hidden="true"
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: 'var(--color-hair)' }}
                    />
                    <span className="truncate text-[var(--color-ink-2)]">{f.label}</span>
                  </span>
                  <span className="shrink-0 text-[11px] text-[var(--color-muted)]">{f.tab}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {data.tabViews.length > 0 ? (
        <section className="card p-4">
          <h2 className="mb-3 text-sm font-semibold">Tab visits</h2>
          <ul className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            {data.tabViews.map((t) => (
              <li key={t.tab} className="flex items-baseline gap-2">
                <span className="font-medium">{t.tab}</span>
                <span className="tabular-nums text-[var(--color-muted)]">{t.count}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="card p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">About this log</h2>
            <p className="mt-1 max-w-2xl text-[11px] leading-relaxed text-[var(--color-muted)]">
              Everything here is recorded <strong>on this machine only</strong> and written to the
              same local database as your finances. Nothing is sent anywhere — there is no network
              call, no analytics service, no account. It records which features you use and when,
              not the amounts you enter.
            </p>
          </div>
          <button type="button" className="btn btn-danger" onClick={onClear} disabled={busy}>
            Clear the log
          </button>
        </div>
      </section>
    </div>
  );
}

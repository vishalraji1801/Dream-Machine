import { useState } from 'react';
import { formatDate, money } from '../lib/format.js';

const MODES = [
  { key: 'byCategory', label: 'By category' },
  { key: 'byEntry', label: 'Single entries' },
];

export default function HighestSpend({ data }) {
  const [mode, setMode] = useState('byCategory');
  if (!data) return null;

  const rows = data[mode] ?? [];
  const max = rows.length > 0 ? Math.max(...rows.map((r) => r.amount)) : 0;

  return (
    <section className="card p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Highest spending</h2>
          <p className="text-xs text-[var(--color-muted)]">
            {money(data.total)} out this month, ranked
          </p>
        </div>
        <div className="flex overflow-hidden rounded-lg border border-[var(--color-hair)]" role="group">
          {MODES.map((m) => (
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

      {rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-[var(--color-muted)]">
          Nothing spent this month yet.
        </p>
      ) : (
        <ol className="space-y-2.5">
          {rows.map((row, i) => (
            <li key={row.key}>
              <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
                <span className="flex min-w-0 items-baseline gap-2">
                  <span className="w-4 shrink-0 text-xs tabular-nums text-[var(--color-muted)]">
                    {i + 1}
                  </span>
                  <span className="truncate font-medium">{row.label}</span>
                  {row.date ? (
                    <span className="shrink-0 text-xs text-[var(--color-muted)]">
                      {formatDate(row.date)}
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
                    width: `${max > 0 ? Math.max((row.amount / max) * 100, 1.5) : 0}%`,
                    backgroundColor: 'var(--color-s2)',
                    borderRadius: '2px 4px 4px 2px',
                  }}
                />
              </div>
            </li>
          ))}
        </ol>
      )}

      <p className="mt-3 border-t border-[var(--color-line)] pt-3 text-[11px] text-[var(--color-muted)]">
        Outflows only — income is excluded. Bars are relative to the largest item; the
        percentage is its share of the month's total spend.
      </p>
    </section>
  );
}

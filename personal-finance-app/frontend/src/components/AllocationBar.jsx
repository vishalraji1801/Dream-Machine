import { money } from '../lib/format.js';

const SEGMENTS = [
  {
    key: 'deployed',
    name: 'Deployed',
    token: 's1',
    formula: 'deposits + reinvested − principal received',
  },
  {
    key: 'idle',
    name: 'Idle cash',
    token: 's3',
    formula: 'paid back − reinvested − withdrawn',
  },
  {
    key: 'withdrawn',
    name: 'Withdrawn',
    token: 's2',
    formula: 'sum of all withdrawals',
  },
];

export default function AllocationBar({ allocation, warnings }) {
  // A negative bucket means the ledger is inconsistent — never render it as width.
  const values = SEGMENTS.map((s) => ({
    ...s,
    raw: allocation[s.key] ?? 0,
    plotted: Math.max(allocation[s.key] ?? 0, 0),
  }));

  const total = values.reduce((sum, s) => sum + s.plotted, 0);

  return (
    <div>
      {total > 0 ? (
        <div
          className="flex h-6 w-full overflow-hidden rounded-md"
          style={{ gap: '2px', backgroundColor: 'var(--color-surface)' }}
          role="img"
          aria-label={values.map((s) => `${s.name} ${money(s.raw)}`).join(', ')}
        >
          {values
            .filter((s) => s.plotted > 0)
            .map((s, i, shown) => (
              <div
                key={s.key}
                style={{
                  width: `${(s.plotted / total) * 100}%`,
                  backgroundColor: `var(--color-${s.token})`,
                  borderTopLeftRadius: i === 0 ? 4 : 0,
                  borderBottomLeftRadius: i === 0 ? 4 : 0,
                  borderTopRightRadius: i === shown.length - 1 ? 4 : 0,
                  borderBottomRightRadius: i === shown.length - 1 ? 4 : 0,
                }}
              />
            ))}
        </div>
      ) : (
        <div className="flex h-6 w-full items-center rounded-md bg-[var(--color-raised)] px-2 text-[11px] text-[var(--color-muted)]">
          Nothing allocated yet
        </div>
      )}

      <dl className="mt-3 space-y-2">
        {values.map((s) => {
          const negative = s.raw < -0.01;
          return (
            <div key={s.key} className="flex items-baseline justify-between gap-3">
              <dt className="flex min-w-0 items-center gap-2 text-sm">
                <span
                  aria-hidden="true"
                  className="h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={{ backgroundColor: `var(--color-${s.token})` }}
                />
                <span className="truncate">
                  {s.name}
                  <span className="ml-1.5 text-[11px] text-[var(--color-muted)]">{s.formula}</span>
                </span>
              </dt>
              <dd className="shrink-0 text-right tabular-nums">
                <span
                  className="text-sm font-semibold"
                  style={{ color: negative ? 'var(--color-critical)' : 'var(--color-ink)' }}
                >
                  {negative ? money(s.raw) : money(s.plotted)}
                </span>
                {total > 0 && !negative ? (
                  <span className="ml-2 text-[11px] text-[var(--color-muted)]">
                    {((s.plotted / total) * 100).toFixed(1)}%
                  </span>
                ) : null}
              </dd>
            </div>
          );
        })}
      </dl>

      {warnings.map((w) => (
        <p
          key={w}
          className="mt-3 flex gap-2 rounded-md p-2 text-xs"
          style={{
            backgroundColor: 'color-mix(in srgb, var(--color-critical) 10%, transparent)',
            color: 'var(--color-critical)',
          }}
        >
          <span aria-hidden="true">⚠</span>
          <span>{w}</span>
        </p>
      ))}
    </div>
  );
}

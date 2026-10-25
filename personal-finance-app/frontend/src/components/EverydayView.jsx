import { formatDate, money, moneyExact } from '../lib/format.js';
import HighestSpend from './HighestSpend.jsx';

function Tile({ label, inAmt, outAmt, net, note }) {
  return (
    <div className="card p-4">
      <p className="label mb-1">{label}</p>
      <p
        className="text-2xl font-semibold"
        style={{ color: net > 0 ? 'var(--color-good-text)' : net < 0 ? 'var(--color-critical)' : undefined }}
      >
        {net > 0 ? '+' : ''}
        {money(net)}
      </p>
      <p className="mt-1 text-xs text-[var(--color-muted)]">
        {note ?? (
          <>
            in {money(inAmt)} · out {money(outAmt)}
          </>
        )}
      </p>
    </div>
  );
}

function dayLabel(iso, today) {
  if (iso === today) return 'Today';
  const d = new Date(`${iso}T00:00:00Z`);
  const t = new Date(`${today}T00:00:00Z`);
  if ((t - d) / 86400000 === 1) return 'Yesterday';
  return formatDate(iso);
}

export default function EverydayView({ summary, onEdit, onDelete }) {
  const { totals, savingsRate, days, today, runningBalance } = summary;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Tile label="Today" inAmt={totals.today.in} outAmt={totals.today.out} net={totals.today.net} />
        <Tile label="This week" inAmt={totals.week.in} outAmt={totals.week.out} net={totals.week.net} />
        <Tile label="This month" inAmt={totals.month.in} outAmt={totals.month.out} net={totals.month.net} />
        <Tile
          label="Saved this month"
          net={totals.month.net}
          note={
            savingsRate === null
              ? 'Log income to see a savings rate'
              : `${savingsRate}% of ${money(totals.month.in)} income`
          }
        />
      </div>

      <HighestSpend data={summary.highestSpend} />

      <section className="card overflow-hidden">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--color-line)] px-4 py-3">
          <h2 className="text-sm font-semibold">
            Daily log
            <span className="ml-2 font-normal text-[var(--color-muted)]">
              {summary.entryCount} {summary.entryCount === 1 ? 'entry' : 'entries'}
            </span>
          </h2>
          <p className="text-xs text-[var(--color-ink-2)]">
            Running net{' '}
            <span className="font-semibold tabular-nums text-[var(--color-ink)]">
              {money(runningBalance)}
            </span>
          </p>
        </header>

        {days.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-[var(--color-muted)]">
            Nothing logged yet — add your first entry above.
          </p>
        ) : (
          <ul>
            {days.map((day) => (
              <li key={day.date} className="border-b border-[var(--color-line)] last:border-0">
                <div className="flex items-baseline justify-between gap-3 bg-[var(--color-raised)] px-4 py-1.5">
                  <span className="text-xs font-semibold">{dayLabel(day.date, today)}</span>
                  <span className="text-xs tabular-nums text-[var(--color-ink-2)]">
                    {day.in > 0 ? (
                      <span style={{ color: 'var(--color-good-text)' }}>+{money(day.in)}</span>
                    ) : null}
                    {day.in > 0 && day.out > 0 ? ' · ' : ''}
                    {day.out > 0 ? <span>−{money(day.out)}</span> : null}
                  </span>
                </div>

                {day.entries.map((e) => {
                  const isIn = e.direction === 'in';
                  return (
                    <div
                      key={e.id}
                      className="flex items-center justify-between gap-3 px-4 py-2 text-sm"
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <span
                          aria-hidden="true"
                          className="h-2 w-2 shrink-0 rounded-full"
                          style={{
                            backgroundColor: isIn ? 'var(--color-s3)' : 'var(--color-s2)',
                          }}
                        />
                        <span className="truncate font-medium">{e.category}</span>
                        {e.note ? (
                          <span className="truncate text-xs text-[var(--color-muted)]">{e.note}</span>
                        ) : null}
                      </span>
                      <span className="flex shrink-0 items-center gap-2">
                        <span
                          className="font-semibold tabular-nums"
                          style={{ color: isIn ? 'var(--color-good-text)' : undefined }}
                        >
                          {isIn ? '+' : '−'}
                          {moneyExact(e.amount)}
                        </span>
                        <button type="button" className="btn px-2 py-0.5 text-xs" onClick={() => onEdit(e)}>
                          Edit
                        </button>
                        <button
                          type="button"
                          className="btn btn-danger px-2 py-0.5 text-xs"
                          onClick={() => onDelete(e)}
                        >
                          Delete
                        </button>
                      </span>
                    </div>
                  );
                })}
              </li>
            ))}
          </ul>
        )}

        <p className="border-t border-[var(--color-line)] px-4 py-2 text-[11px] text-[var(--color-muted)]">
          Money out here is the same data the Spending tab breaks down by category — logged once,
          counted once. Running net is the sum of what you have logged, not a bank balance.
        </p>
      </section>
    </div>
  );
}

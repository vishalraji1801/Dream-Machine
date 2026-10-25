import { formatDate, moneyExact } from '../lib/format.js';

export default function MfLog({ rows, onEdit, onDelete, editingId }) {
  return (
    <section className="card overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--color-line)] px-4 py-3">
        <h2 className="text-sm font-semibold">
          Fund transactions
          <span className="ml-2 font-normal text-[var(--color-muted)]">
            {rows.length} {rows.length === 1 ? 'entry' : 'entries'}
          </span>
        </h2>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-[var(--color-line)] text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
              <th scope="col" className="px-3 py-2 text-left font-semibold">Date</th>
              <th scope="col" className="px-3 py-2 text-left font-semibold">Fund</th>
              <th scope="col" className="px-3 py-2 text-left font-semibold">Type</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Amount</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Units</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">NAV</th>
              <th scope="col" className="px-3 py-2 text-left font-semibold">Source</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((row) => {
              const isBuy = row.type === 'buy';
              return (
                <tr
                  key={row.id}
                  className="border-b border-[var(--color-line)] last:border-0"
                  style={{ backgroundColor: editingId === row.id ? 'var(--color-raised)' : undefined }}
                >
                  <td className="px-3 py-2 whitespace-nowrap text-[var(--color-ink-2)]">
                    {formatDate(row.date)}
                  </td>
                  <td className="px-3 py-2 font-medium">{row.fund}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <span className="inline-flex items-center gap-2">
                      <span
                        aria-hidden="true"
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ backgroundColor: isBuy ? 'var(--color-s1)' : 'var(--color-s2)' }}
                      />
                      {isBuy ? 'Buy' : 'Sell'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap font-medium">
                    {moneyExact(row.amount)}
                  </td>
                  <td className="px-3 py-2 text-right text-[var(--color-ink-2)]">
                    {row.units == null ? '—' : row.units}
                  </td>
                  <td className="px-3 py-2 text-right text-[var(--color-ink-2)]">
                    {row.nav == null ? '—' : row.nav}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {!isBuy ? (
                      <span className="text-[var(--color-muted)]">—</span>
                    ) : row.source === 'lenden' ? (
                      <span style={{ color: 'var(--color-good-text)' }}>LenDen returns</span>
                    ) : (
                      <span className="text-[var(--color-muted)]">Bank</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <div className="flex justify-end gap-1">
                      <button type="button" className="btn px-2 py-1" onClick={() => onEdit(row)}>
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn btn-danger px-2 py-1"
                        onClick={() => onDelete(row)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-3 py-10 text-center text-sm text-[var(--color-muted)]">
                  Nothing logged yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

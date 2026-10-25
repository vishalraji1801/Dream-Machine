import { formatDate, moneyExact } from '../lib/format.js';

const COLUMNS = [
  { key: 'date', label: 'Date', sortable: true, align: 'left' },
  { key: 'category', label: 'Category', sortable: true, align: 'left' },
  { key: 'note', label: 'Note', sortable: false, align: 'left' },
  { key: 'amount', label: 'Amount', sortable: true, align: 'right' },
];

export default function ExpenseTable({ rows, sort, dir, onSort, onEdit, onDelete, editingId, monthLabel }) {
  const total = rows.reduce((sum, r) => sum + r.amount, 0);

  return (
    <section className="card overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--color-line)] px-4 py-3">
        <h2 className="text-sm font-semibold">
          Expenses
          <span className="ml-2 font-normal text-[var(--color-muted)]">
            {monthLabel} · {rows.length} {rows.length === 1 ? 'entry' : 'entries'}
          </span>
        </h2>
        <p className="text-sm tabular-nums text-[var(--color-ink-2)]">
          Total <span className="font-semibold text-[var(--color-ink)]">{moneyExact(total)}</span>
        </p>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] text-sm">
          <thead>
            <tr className="border-b border-[var(--color-line)] text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  className="px-4 py-2 font-semibold"
                  style={{ textAlign: c.align }}
                  aria-sort={sort === c.key ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                >
                  {c.sortable ? (
                    <button
                      type="button"
                      onClick={() => onSort(c.key)}
                      className="inline-flex items-center gap-1 hover:text-[var(--color-ink)]"
                    >
                      {c.label}
                      <span aria-hidden="true" style={{ opacity: sort === c.key ? 1 : 0.25 }}>
                        {sort === c.key && dir === 'asc' ? '▲' : '▼'}
                      </span>
                    </button>
                  ) : (
                    c.label
                  )}
                </th>
              ))}
              <th scope="col" className="px-4 py-2 text-right font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((row) => (
              <tr
                key={row.id}
                className="border-b border-[var(--color-line)] last:border-0"
                style={{ backgroundColor: editingId === row.id ? 'var(--color-raised)' : undefined }}
              >
                <td className="px-4 py-2 whitespace-nowrap text-[var(--color-ink-2)]">
                  {formatDate(row.date)}
                </td>
                <td className="px-4 py-2 whitespace-nowrap font-medium">{row.category}</td>
                <td className="max-w-[280px] truncate px-4 py-2 text-[var(--color-ink-2)]">
                  {row.note || '—'}
                </td>
                <td className="px-4 py-2 text-right font-medium whitespace-nowrap">
                  {moneyExact(row.amount)}
                </td>
                <td className="px-4 py-2 text-right whitespace-nowrap">
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
            ))}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-sm text-[var(--color-muted)]">
                  Nothing logged for {monthLabel}. Add your first expense above.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

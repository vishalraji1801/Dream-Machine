import { LOAN_TYPE_META, formatDate, moneyExact } from '../lib/format.js';

const TYPE_STYLE = {
  drawdown: { dot: 'var(--color-s2)', sign: '+' },
  repayment: { dot: 'var(--color-s3)', sign: '−' },
  interest: { dot: 'var(--color-critical)', sign: '+' },
};

const COLUMNS = [
  { key: 'date', label: 'Date', sortable: true, align: 'left' },
  { key: 'type', label: 'Type', sortable: true, align: 'left' },
  { key: 'note', label: 'Note', sortable: false, align: 'left' },
  { key: 'amount', label: 'Amount', sortable: true, align: 'right' },
];

export default function LoanTable({ rows, sort, dir, onSort, onEdit, onDelete, editingId, filter, onFilter }) {
  const visible = filter === 'all' ? rows : rows.filter((r) => r.type === filter);

  return (
    <section className="card overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--color-line)] px-4 py-3">
        <h2 className="text-sm font-semibold">
          Loan log
          <span className="ml-2 font-normal text-[var(--color-muted)]">
            {visible.length} {visible.length === 1 ? 'entry' : 'entries'}
          </span>
        </h2>
        <div className="flex flex-wrap gap-1">
          {['all', ...Object.keys(LOAN_TYPE_META)].map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => onFilter(t)}
              className="rounded-md px-2 py-1 text-xs font-medium"
              style={{
                backgroundColor: filter === t ? 'var(--color-raised)' : 'transparent',
                color: filter === t ? 'var(--color-ink)' : 'var(--color-muted)',
              }}
            >
              {t === 'all' ? 'All' : LOAN_TYPE_META[t].label}
            </button>
          ))}
        </div>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[600px] text-sm">
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
            {visible.map((row) => {
              const meta = TYPE_STYLE[row.type] ?? TYPE_STYLE.drawdown;
              return (
                <tr
                  key={row.id}
                  className="border-b border-[var(--color-line)] last:border-0"
                  style={{ backgroundColor: editingId === row.id ? 'var(--color-raised)' : undefined }}
                >
                  <td className="px-4 py-2 whitespace-nowrap text-[var(--color-ink-2)]">
                    {formatDate(row.date)}
                  </td>
                  <td className="px-4 py-2 whitespace-nowrap">
                    <span className="inline-flex items-center gap-2">
                      <span
                        aria-hidden="true"
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ backgroundColor: meta.dot }}
                      />
                      {LOAN_TYPE_META[row.type]?.label ?? row.type}
                    </span>
                  </td>
                  <td className="max-w-[300px] truncate px-4 py-2 text-[var(--color-ink-2)]">
                    {row.note || '—'}
                  </td>
                  <td className="px-4 py-2 text-right font-medium whitespace-nowrap">
                    <span className="mr-1 text-[var(--color-muted)]" aria-hidden="true">{meta.sign}</span>
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
              );
            })}
            {visible.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-sm text-[var(--color-muted)]">
                  {rows.length === 0
                    ? 'Nothing logged yet — start with the amount you drew from the facility.'
                    : 'No entries of this type.'}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

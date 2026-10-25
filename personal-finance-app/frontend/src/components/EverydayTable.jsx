import { useState } from 'react';
import { formatDate, moneyExact } from '../lib/format.js';

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'out', label: 'Money out' },
  { key: 'in', label: 'Money in' },
];

const COLUMNS = [
  { key: 'date', label: 'Date', align: 'left' },
  { key: 'direction', label: 'Type', align: 'left' },
  { key: 'category', label: 'Category', align: 'left' },
  { key: 'note', label: 'Note', align: 'left' },
  { key: 'amount', label: 'Amount', align: 'right' },
];

const SORTABLE = new Set(['date', 'category', 'amount']);

export default function EverydayTable({ rows, onEdit, onDelete, editingId }) {
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState('date');
  const [dir, setDir] = useState('desc');

  function toggleSort(key) {
    if (!SORTABLE.has(key)) return;
    if (key === sort) setDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSort(key);
      setDir(key === 'date' ? 'desc' : 'asc');
    }
  }

  const visible = rows
    .filter((r) => (filter === 'all' ? true : r.direction === filter))
    .slice()
    .sort((a, b) => {
      const mul = dir === 'asc' ? 1 : -1;
      if (sort === 'amount') return (a.amount - b.amount) * mul;
      if (sort === 'category') return a.category.localeCompare(b.category) * mul;
      return (a.date.localeCompare(b.date) || a.id - b.id) * mul;
    });

  const totalIn = visible.filter((r) => r.direction === 'in').reduce((s, r) => s + r.amount, 0);
  const totalOut = visible.filter((r) => r.direction === 'out').reduce((s, r) => s + r.amount, 0);

  return (
    <section className="card overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--color-line)] px-4 py-3">
        <h2 className="text-sm font-semibold">
          Transaction log
          <span className="ml-2 font-normal text-[var(--color-muted)]">
            {visible.length} {visible.length === 1 ? 'entry' : 'entries'}
          </span>
        </h2>
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-xs tabular-nums text-[var(--color-ink-2)]">
            <span style={{ color: 'var(--color-good-text)' }}>+{moneyExact(totalIn)}</span>
            {' · '}
            <span>−{moneyExact(totalOut)}</span>
          </p>
          <div className="flex flex-wrap gap-1">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className="rounded-md px-2 py-1 text-xs font-medium"
                style={{
                  backgroundColor: filter === f.key ? 'var(--color-raised)' : 'transparent',
                  color: filter === f.key ? 'var(--color-ink)' : 'var(--color-muted)',
                }}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
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
                  {SORTABLE.has(c.key) ? (
                    <button
                      type="button"
                      onClick={() => toggleSort(c.key)}
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
              const isIn = row.direction === 'in';
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
                        style={{ backgroundColor: isIn ? 'var(--color-s3)' : 'var(--color-s2)' }}
                      />
                      {isIn ? 'In' : 'Out'}
                    </span>
                  </td>
                  <td className="px-4 py-2 whitespace-nowrap font-medium">{row.category}</td>
                  <td className="max-w-[260px] truncate px-4 py-2 text-[var(--color-ink-2)]">
                    {row.note || '—'}
                  </td>
                  <td
                    className="px-4 py-2 text-right font-medium whitespace-nowrap"
                    style={{ color: isIn ? 'var(--color-good-text)' : undefined }}
                  >
                    {isIn ? '+' : '−'}
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
                <td colSpan={6} className="px-4 py-10 text-center text-sm text-[var(--color-muted)]">
                  {rows.length === 0 ? 'Nothing logged yet.' : 'No entries of this type.'}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

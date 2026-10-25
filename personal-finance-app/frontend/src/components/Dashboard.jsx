import { useState } from 'react';
import { XIRR_LIMIT, formatDate, money, percent } from '../lib/format.js';
import AllocationBar from './AllocationBar.jsx';
import GrowthChart, { GrowthLegend } from './GrowthChart.jsx';
import PeriodBreakdown from './PeriodBreakdown.jsx';
import ProjectionCard from './ProjectionCard.jsx';

/** LenDen reports only a running total of defaulted loans, so this is hand-maintained. */
function NpaTile({ npa, onSave, busy }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState(null);

  function startEdit() {
    setDraft(npa.amount ? String(npa.amount) : '');
    setError(null);
    setEditing(true);
  }

  async function save(e) {
    e.preventDefault();
    setError(null);
    try {
      await onSave({ amount: draft.trim() === '' ? 0 : draft });
      setEditing(false);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="card p-4">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <p className="label mb-0">Non-performing</p>
        {!editing ? (
          <button
            type="button"
            onClick={startEdit}
            className="text-[10px] font-semibold text-[var(--color-s1)] hover:underline"
          >
            edit
          </button>
        ) : null}
      </div>

      {editing ? (
        <form onSubmit={save} className="space-y-2">
          <input
            type="text"
            inputMode="decimal"
            autoFocus
            className="field"
            placeholder="0.00"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="flex gap-1">
            <button type="submit" className="btn btn-primary flex-1 px-2 py-1" disabled={busy}>
              Save
            </button>
            <button type="button" className="btn px-2 py-1" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
          {error ? <p className="text-xs text-[var(--color-critical)]">{error}</p> : null}
        </form>
      ) : (
        <>
          <p
            className="text-2xl font-semibold"
            style={{ color: npa.amount > 0 ? 'var(--color-critical)' : undefined }}
          >
            {npa.amount > 0 ? `−${money(npa.amount)}` : money(0)}
          </p>
          <p className="mt-1 text-xs text-[var(--color-muted)]">
            {npa.updatedAt
              ? `Deducted · updated ${formatDate(npa.updatedAt.slice(0, 10))}`
              : 'Deducted from your value'}
          </p>
        </>
      )}
    </div>
  );
}

function StatTile({ label, value, note, accent }) {
  return (
    <div className="card p-4">
      <p className="label mb-1">{label}</p>
      <p className="text-2xl font-semibold" style={accent ? { color: accent } : undefined}>
        {value}
      </p>
      {note ? <p className="mt-1 text-xs text-[var(--color-muted)]">{note}</p> : null}
    </div>
  );
}

function xirrNote(summary) {
  const { xirr, totals } = summary;
  if (totals.deposited === 0) return 'Needs at least one deposit';
  if (xirr === null) return 'Not enough dated flows yet';
  if (Math.abs(xirr) > XIRR_LIMIT) return 'Too short a history to annualise';
  return 'Annualised, money-weighted';
}

export default function Dashboard({ summary, themeKey, periods, grain, onGrainChange, onSaveNpa, busy, projection, onProjectionChange }) {
  const { totals, portfolioValue, grossValue, npa, allocation, warnings, xirr } = summary;
  const gain = totals.interestEarned;
  const gainPct = totals.deposited > 0 ? (gain / totals.deposited) * 100 : null;
  const xirrShown = xirr !== null && Math.abs(xirr) <= XIRR_LIMIT;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <div className="card flex flex-col justify-center p-5">
          <p className="label mb-1">Current portfolio value</p>
          <p className="text-5xl font-semibold tracking-tight">{money(portfolioValue)}</p>
          <p className="mt-2 text-sm text-[var(--color-ink-2)]">
            {money(totals.deposited)} deposited
            {gain !== 0 ? (
              <>
                {' · '}
                <span style={{ color: gain > 0 ? 'var(--color-good-text)' : 'var(--color-critical)' }}>
                  {gain > 0 ? '+' : ''}
                  {money(gain)} interest
                  {gainPct !== null ? ` (${gainPct.toFixed(2)}%)` : ''}
                </span>
              </>
            ) : null}
          </p>
          {npa.amount > 0 ? (
            <p className="mt-1 text-sm" style={{ color: 'var(--color-critical)' }}>
              −{money(npa.amount)} non-performing deducted
              <span className="ml-1 text-xs text-[var(--color-muted)]">
                (from {money(grossValue)})
              </span>
            </p>
          ) : null}
          <p className="mt-1 text-xs text-[var(--color-muted)]">
            As of {formatDate(summary.asOf)} · deposited + interest − withdrawn
            {npa.amount > 0 ? ' − non-performing' : ''}
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
          <StatTile
            label="Total deposited"
            value={money(totals.deposited)}
            note="Capital you put in"
          />
          <StatTile
            label="Interest earned"
            value={money(totals.interestEarned)}
            note="Across all payouts"
            accent={totals.interestEarned > 0 ? 'var(--color-good-text)' : undefined}
          />
          <NpaTile npa={npa} onSave={onSaveNpa} busy={busy} />
          <StatTile
            label="XIRR"
            value={percent(xirr)}
            note={xirrNote(summary)}
            accent={xirrShown ? (xirr >= 0 ? 'var(--color-good-text)' : 'var(--color-critical)') : undefined}
          />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <section className="card p-4">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">Portfolio growth</h2>
              <p className="text-xs text-[var(--color-muted)]">
                Cumulative value against capital deployed
                {npa.amount > 0 ? ' — before non-performing' : ''}
              </p>
            </div>
            <GrowthLegend />
          </div>
          <GrowthChart data={summary.growth} themeKey={themeKey} />
        </section>

        <section className="card p-4">
          <div className="mb-3">
            <h2 className="text-sm font-semibold">Where the money sits</h2>
            <p className="text-xs text-[var(--color-muted)]">Deployed vs idle vs withdrawn</p>
          </div>
          <AllocationBar allocation={allocation} warnings={warnings} />
          <p className="mt-3 border-t border-[var(--color-line)] pt-3 text-[11px] leading-relaxed text-[var(--color-muted)]">
            Deployed + idle always equals portfolio value ({money(portfolioValue)}). Deployed is
            shown after deducting non-performing loans. Reinvesting moves money from idle to
            deployed; it is not a new deposit and does not affect XIRR.
          </p>
        </section>
      </div>

      <PeriodBreakdown
        data={periods}
        grain={grain}
        onGrainChange={onGrainChange}
        themeKey={themeKey}
      />

      <ProjectionCard
        data={projection}
        onChange={onProjectionChange}
        themeKey={themeKey}
        busy={busy}
      />
    </div>
  );
}

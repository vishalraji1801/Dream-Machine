import { useState } from 'react';
import { XIRR_LIMIT, formatDate, money, moneyExact, percent } from '../lib/format.js';

function Tile({ label, value, note, accent }) {
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

/** NAV has to be typed in — there is no price feed, so each fund is valued by hand. */
function NavCell({ holding, onSaveNav, busy }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');

  async function save(e) {
    e.preventDefault();
    try {
      await onSaveNav({ fund: holding.fund, nav: draft });
      setEditing(false);
    } catch {
      /* the page-level banner reports it */
    }
  }

  if (editing) {
    return (
      <form onSubmit={save} className="flex items-center justify-end gap-1">
        <input
          autoFocus
          className="field w-24 text-right"
          inputMode="decimal"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit" className="btn px-2 py-1" disabled={busy}>Save</button>
      </form>
    );
  }

  return (
    <button
      type="button"
      className="text-right hover:underline"
      onClick={() => {
        setDraft(holding.nav === null ? '' : String(holding.nav));
        setEditing(true);
      }}
    >
      {holding.nav === null ? (
        <span style={{ color: 'var(--color-critical)' }}>set NAV</span>
      ) : (
        <>
          <span className="font-medium">{holding.nav}</span>
          {holding.navAsOf ? (
            <span className="block text-[10px] text-[var(--color-muted)]">
              {formatDate(holding.navAsOf)}
            </span>
          ) : null}
        </>
      )}
    </button>
  );
}

export default function MutualFundView({ summary, onSaveNav, busy }) {
  const {
    holdings,
    totals,
    currentValue,
    realisedGain,
    unrealisedGain,
    totalGain,
    returnPct,
    lendenShare,
    xirr,
    warnings,
  } = summary;

  const open = holdings.filter((h) => !h.closed);
  const closed = holdings.filter((h) => h.closed);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <div className="card flex flex-col justify-center p-5">
          <p className="label mb-1">Current value</p>
          <p className="text-5xl font-semibold tracking-tight">{money(currentValue)}</p>
          <p className="mt-2 text-sm text-[var(--color-ink-2)]">
            {money(totals.costBasis)} invested
            {Math.abs(unrealisedGain) > 0.5 ? (
              <>
                {' · '}
                <span style={{ color: unrealisedGain >= 0 ? 'var(--color-good-text)' : 'var(--color-critical)' }}>
                  {unrealisedGain >= 0 ? '+' : ''}
                  {money(unrealisedGain)}
                  {returnPct !== null ? ` (${returnPct}%)` : ''}
                </span>
              </>
            ) : null}
          </p>
          {summary.unvaluedCost > 0 ? (
            <p className="mt-1 text-xs" style={{ color: 'var(--color-critical)' }}>
              Excludes {money(summary.unvaluedCost)} in funds with no NAV set
            </p>
          ) : null}
          <p className="mt-1 text-xs text-[var(--color-muted)]">
            As of {formatDate(summary.asOf)} · {summary.fundCount}{' '}
            {summary.fundCount === 1 ? 'fund' : 'funds'} held
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
          <Tile label="Invested" value={money(totals.costBasis)} note="Cost of what you still hold" />
          <Tile
            label="Gain"
            value={money(totalGain)}
            note={`${money(unrealisedGain)} on paper · ${money(realisedGain)} banked`}
            accent={totalGain > 0 ? 'var(--color-good-text)' : totalGain < 0 ? 'var(--color-critical)' : undefined}
          />
          <Tile
            label="From LenDen"
            value={lendenShare === null ? '—' : `${lendenShare}%`}
            note={`${money(totals.fromLenden)} of ${money(totals.invested)} put in`}
          />
          <Tile
            label="XIRR"
            value={percent(xirr)}
            note={
              xirr === null
                ? 'Needs a valued holding'
                : Math.abs(xirr) > XIRR_LIMIT
                  ? 'Too short a history'
                  : 'Annualised, money-weighted'
            }
            accent={
              xirr !== null && Math.abs(xirr) <= XIRR_LIMIT
                ? xirr >= 0
                  ? 'var(--color-good-text)'
                  : 'var(--color-critical)'
                : undefined
            }
          />
        </div>
      </div>

      {warnings.map((w) => (
        <p
          key={w}
          className="flex gap-2 rounded-lg p-3 text-sm"
          style={{
            backgroundColor: 'color-mix(in srgb, var(--color-critical) 10%, transparent)',
            color: 'var(--color-critical)',
          }}
        >
          <span aria-hidden="true">⚠</span>
          <span>{w}</span>
        </p>
      ))}

      <section className="card overflow-hidden">
        <header className="border-b border-[var(--color-line)] px-4 py-3">
          <h2 className="text-sm font-semibold">
            Holdings
            <span className="ml-2 font-normal text-[var(--color-muted)]">
              {open.length} open{closed.length > 0 ? ` · ${closed.length} closed` : ''}
            </span>
          </h2>
          <p className="text-xs text-[var(--color-muted)]">Click a NAV to update it</p>
        </header>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="border-b border-[var(--color-line)] text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
                <th scope="col" className="px-3 py-2 text-left font-semibold">Fund</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Units</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Invested</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">NAV</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Value</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Gain</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">From LenDen</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {holdings.map((h) => (
                <tr
                  key={h.fund}
                  className="border-b border-[var(--color-line)] last:border-0"
                  style={{ opacity: h.closed ? 0.55 : 1 }}
                >
                  <td className="px-3 py-2 font-medium">
                    {h.fund}
                    {h.closed ? (
                      <span className="ml-2 text-[10px] uppercase text-[var(--color-muted)]">closed</span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-right text-[var(--color-ink-2)]">
                    {h.units > 0 ? h.units : '—'}
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">{money(h.costBasis)}</td>
                  <td className="px-3 py-2 text-right">
                    {h.closed ? '—' : <NavCell holding={h} onSaveNav={onSaveNav} busy={busy} />}
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap font-semibold">
                    {h.currentValue === null ? '—' : money(h.currentValue)}
                  </td>
                  <td
                    className="px-3 py-2 text-right whitespace-nowrap"
                    style={{
                      color:
                        h.unrealisedGain === null
                          ? undefined
                          : h.unrealisedGain >= 0
                            ? 'var(--color-good-text)'
                            : 'var(--color-critical)',
                    }}
                  >
                    {h.unrealisedGain === null ? '—' : (
                      <>
                        {h.unrealisedGain >= 0 ? '+' : ''}
                        {money(h.unrealisedGain)}
                        {h.returnPct !== null ? (
                          <span className="block text-[10px] text-[var(--color-muted)]">
                            {h.returnPct}%
                          </span>
                        ) : null}
                      </>
                    )}
                    {h.realisedGain !== 0 ? (
                      <span className="block text-[10px] text-[var(--color-muted)]">
                        {moneyExact(h.realisedGain)} banked
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-right text-[var(--color-ink-2)]">
                    {h.fromLenden > 0 ? money(h.fromLenden) : '—'}
                  </td>
                </tr>
              ))}
              {holdings.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-10 text-center text-sm text-[var(--color-muted)]">
                    No fund transactions yet — add your first purchase below.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <p className="border-t border-[var(--color-line)] px-4 py-2 text-[11px] leading-relaxed text-[var(--color-muted)]">
          Invested is the cost of units you still hold — selling reduces it proportionally at
          average cost, so it means money still at work rather than money ever spent. Gains on
          units you have sold show separately as banked. Funds with no NAV are left out of the
          total rather than assumed to be worth their cost.
        </p>
      </section>
    </div>
  );
}

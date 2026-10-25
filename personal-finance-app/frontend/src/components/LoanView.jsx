import { useEffect, useState } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { compactMoney, formatDate, money, moneyExact } from '../lib/format.js';
import { useChartTheme } from '../lib/useChartTheme.js';
import LoanCalculator from './LoanCalculator.jsx';
import LoanComparator from './LoanComparator.jsx';
import PayoffPlan from './PayoffPlan.jsx';
import RepaymentSchedule from './RepaymentSchedule.jsx';

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

function FacilitySettings({ settings, onSave, busy }) {
  const [limit, setLimit] = useState('');
  const [rate, setRate] = useState('');
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLimit(settings.limit === null ? '' : String(settings.limit));
    setRate(settings.rate === null ? '' : String(settings.rate));
  }, [settings.limit, settings.rate]);

  async function handleSave(e) {
    e.preventDefault();
    setError(null);
    try {
      await onSave({ limit: limit.trim() === '' ? null : limit, rate: rate.trim() === '' ? null : rate });
      setOpen(false);
    } catch (err) {
      setError(err.message);
    }
  }

  if (!open) {
    return (
      <button type="button" className="btn" onClick={() => setOpen(true)}>
        {settings.limit === null ? 'Set facility details' : 'Edit facility'}
      </button>
    );
  }

  return (
    <form onSubmit={handleSave} className="flex flex-wrap items-end gap-2">
      <div>
        <label className="label" htmlFor="loan-limit">Sanctioned limit (₹)</label>
        <input
          id="loan-limit"
          type="text"
          inputMode="decimal"
          className="field w-40"
          placeholder="500000"
          value={limit}
          onChange={(e) => setLimit(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="loan-rate">Interest rate (% p.a.)</label>
        <input
          id="loan-rate"
          type="text"
          inputMode="decimal"
          className="field w-32"
          placeholder="10.5"
          value={rate}
          onChange={(e) => setRate(e.target.value)}
        />
      </div>
      <button type="submit" className="btn btn-primary" disabled={busy}>Save</button>
      <button type="button" className="btn" onClick={() => setOpen(false)}>Cancel</button>
      {error ? <p className="w-full text-xs text-[var(--color-critical)]">{error}</p> : null}
    </form>
  );
}

/** Break-even view: what LenDen earns per month is the ceiling on affordable interest. */
function AffordabilityCard({ afford, rate }) {
  const thin = afford.monthsObserved < 3;

  return (
    <section className="card p-4">
      <div className="mb-3">
        <h2 className="text-sm font-semibold">What you can afford each month</h2>
        <p className="text-xs text-[var(--color-muted)]">
          LenDen interest sets the ceiling on loan interest
        </p>
      </div>

      <p className="label mb-1">Affordable interest per month</p>
      <p className="text-4xl font-semibold tracking-tight" style={{ color: 'var(--color-good-text)' }}>
        {money(afford.earningsPerMonth)}
      </p>
      <p className="mt-1 text-xs text-[var(--color-muted)]">
        {afford.monthsObserved === 0
          ? 'No earning months logged yet'
          : `Averaged over ${afford.monthsElapsed} ${afford.monthsElapsed === 1 ? 'month' : 'months'}, including quiet ones`}
        {afford.lastMonth ? ` · last payout month ${money(afford.lastMonth.interest)}` : ''}
      </p>
      {afford.monthsObserved > 0 && afford.monthsElapsed > afford.monthsObserved ? (
        <p className="mt-1 text-[11px] leading-relaxed text-[var(--color-muted)]">
          Only {afford.monthsObserved} of those {afford.monthsElapsed} months had a payout — on
          earning months alone it averages {money(afford.averageWhenEarning)}, but you still owe
          interest in the quiet ones, so the lower figure is the one to plan against.
        </p>
      ) : null}

      {afford.projectedCost !== null ? (
        <dl className="mt-4 space-y-2 border-t border-[var(--color-line)] pt-3 text-sm">
          <div className="flex items-baseline justify-between gap-3">
            <dt className="text-[var(--color-ink-2)]">
              Your balance costs
              <span className="ml-1 text-[11px] text-[var(--color-muted)]">
                {money(afford.outstanding)} at {rate}%
              </span>
            </dt>
            <dd className="font-semibold tabular-nums">{money(afford.projectedCost)}</dd>
          </div>
          <div className="flex items-baseline justify-between gap-3 border-t border-[var(--color-line)] pt-2">
            <dt className="font-semibold">Headroom</dt>
            <dd
              className="text-lg font-semibold tabular-nums"
              style={{ color: afford.affordable ? 'var(--color-good-text)' : 'var(--color-critical)' }}
            >
              {afford.headroom >= 0 ? '+' : ''}
              {money(afford.headroom)}
            </dd>
          </div>
        </dl>
      ) : (
        <p className="mt-4 border-t border-[var(--color-line)] pt-3 text-xs text-[var(--color-muted)]">
          Set an interest rate on the facility to see what your balance costs each month.
        </p>
      )}

      {afford.maxBalance !== null || afford.breakEvenRate !== null ? (
        <div className="mt-3 space-y-1.5 border-t border-[var(--color-line)] pt-3 text-xs">
          {afford.maxBalance !== null ? (
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[var(--color-muted)]">Balance you can carry at {rate}%</span>
              <span className="font-semibold tabular-nums">{money(afford.maxBalance)}</span>
            </div>
          ) : null}
          {afford.breakEvenRate !== null ? (
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[var(--color-muted)]">Break-even rate on this balance</span>
              <span className="font-semibold tabular-nums">{afford.breakEvenRate}% p.a.</span>
            </div>
          ) : null}
        </div>
      ) : null}

      <p className="mt-3 border-t border-[var(--color-line)] pt-3 text-[11px] leading-relaxed text-[var(--color-muted)]">
        {thin
          ? 'Based on very little history — one or two months of payouts is not a reliable monthly average. Treat this as a rough guide until a few more months accumulate.'
          : 'Based on your actual payouts. LenDen pays at irregular intervals, so a quiet month can still fall below this average.'}
      </p>
    </section>
  );
}

function SpreadCard({ spread }) {
  const good = spread.positive;
  const colour = good ? 'var(--color-good-text)' : 'var(--color-critical)';
  const rateOk = spread.rateSpread !== null && spread.rateSpread >= 0;
  const attr = spread.attribution;

  return (
    <section className="card p-4">
      <div className="mb-3">
        <h2 className="text-sm font-semibold">Is the borrow paying off?</h2>
        <p className="text-xs text-[var(--color-muted)]">
          Borrowed money can't be traced once invested — so here it is two ways
        </p>
      </div>

      {spread.rateSpread !== null ? (
        <div
          className="mb-4 rounded-md p-3"
          style={{
            backgroundColor: rateOk
              ? 'color-mix(in srgb, var(--color-good) 12%, transparent)'
              : 'color-mix(in srgb, var(--color-critical) 10%, transparent)',
          }}
        >
          <p className="label mb-1">Rate spread — the decisive test</p>
          <p className="text-3xl font-semibold" style={{ color: rateOk ? 'var(--color-good-text)' : 'var(--color-critical)' }}>
            {spread.rateSpread >= 0 ? '+' : ''}
            {spread.rateSpread} pts
          </p>
          <p className="mt-1 text-xs text-[var(--color-ink-2)]">
            LenDen yields {spread.portfolioRate}% · loan costs {spread.loanRate}%
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-[var(--color-muted)]">
            {rateOk
              ? 'Every borrowed rupee earns more than it costs, whatever the amount. This holds without needing to know which money earned what.'
              : 'Each borrowed rupee costs more than it earns. Borrowing more makes the gap wider, not smaller.'}
          </p>
        </div>
      ) : null}

      {attr ? (
        <div className="mb-4 border-t border-[var(--color-line)] pt-3">
          <p className="label mb-2">Your share, attributed</p>
          <dl className="space-y-1.5 text-sm">
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-[var(--color-ink-2)]">
                Borrowed share of capital
                <span className="ml-1 text-[11px] text-[var(--color-muted)]">
                  {money(attr.outstanding)} of {money(attr.portfolioValue)}
                </span>
              </dt>
              <dd className="font-semibold tabular-nums">{attr.borrowedShare}%</dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-[var(--color-ink-2)]">Interest credited to it / month</dt>
              <dd className="font-semibold tabular-nums">{moneyExact(attr.attributedPerMonth ?? 0)}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-[var(--color-ink-2)]">Loan costs / month</dt>
              <dd className="font-semibold tabular-nums">−{moneyExact(attr.loanCostPerMonth ?? 0)}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-3 border-t border-[var(--color-line)] pt-1.5">
              <dt className="font-semibold">Net on the borrowed part</dt>
              <dd
                className="text-lg font-semibold tabular-nums"
                style={{ color: attr.worthIt ? 'var(--color-good-text)' : 'var(--color-critical)' }}
              >
                {attr.netPerMonth >= 0 ? '+' : ''}
                {moneyExact(attr.netPerMonth ?? 0)}
              </dd>
            </div>
          </dl>
          <p className="mt-2 text-[11px] leading-relaxed text-[var(--color-muted)]">
            Since {attr.borrowedShare}% of your capital is borrowed, it is credited with{' '}
            {attr.borrowedShare}% of the interest. An assumption, not a measurement — but the
            only defensible way to split earnings that were never separable.
          </p>
        </div>
      ) : null}

      <p className="label mb-2 border-t border-[var(--color-line)] pt-3">Lifetime totals</p>

      <dl className="space-y-2 text-sm">
        <div className="flex items-baseline justify-between gap-3">
          <dt className="text-[var(--color-ink-2)]">Interest earned on LenDen</dt>
          <dd className="font-semibold tabular-nums">{moneyExact(spread.interestEarned)}</dd>
        </div>
        <div className="flex items-baseline justify-between gap-3">
          <dt className="text-[var(--color-ink-2)]">Interest charged on loan</dt>
          <dd className="font-semibold tabular-nums">−{moneyExact(spread.interestCharged)}</dd>
        </div>
        <div className="flex items-baseline justify-between gap-3 border-t border-[var(--color-line)] pt-2">
          <dt className="font-semibold">Net</dt>
          <dd className="text-lg font-semibold tabular-nums" style={{ color: colour }}>
            {spread.net >= 0 ? '+' : ''}
            {moneyExact(spread.net)}
          </dd>
        </div>
      </dl>

      {spread.rateSpread === null ? (
        <p className="mt-3 border-t border-[var(--color-line)] pt-3 text-[11px] text-[var(--color-muted)]">
          Set an interest rate on the facility to compare rates — that comparison is the one
          that does not depend on tracing which rupees earned what.
        </p>
      ) : null}
    </section>
  );
}

function BalanceChart({ data, themeKey }) {
  const colors = useChartTheme(themeKey);
  if (!data || data.length < 2) {
    return (
      <div className="flex h-56 items-center justify-center text-sm text-[var(--color-muted)]">
        Add at least two dated entries to plot the balance.
      </div>
    );
  }

  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="loanWash" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={colors.s2} stopOpacity={0.18} />
              <stop offset="100%" stopColor={colors.s2} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={colors.grid} vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={(d) => formatDate(d).replace(/ \d{4}$/, '')}
            tick={{ fill: colors.muted, fontSize: 11 }}
            axisLine={{ stroke: colors.hair }}
            tickLine={false}
            minTickGap={28}
          />
          <YAxis
            tickFormatter={compactMoney}
            tick={{ fill: colors.muted, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={56}
          />
          <Tooltip
            cursor={{ stroke: colors.hair }}
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <div
                  className="rounded-lg px-3 py-2 text-xs shadow-lg"
                  style={{ backgroundColor: colors.surface, border: `1px solid ${colors.hair}`, color: colors.ink }}
                >
                  <p className="mb-1 font-semibold">{formatDate(label)}</p>
                  <p className="tabular-nums" style={{ color: colors['ink-2'] }}>
                    Outstanding{' '}
                    <span style={{ color: colors.ink }}>{money(payload[0].payload.outstanding)}</span>
                  </p>
                </div>
              ) : null
            }
          />
          <Area
            type="stepAfter"
            dataKey="outstanding"
            stroke={colors.s2}
            strokeWidth={2}
            fill="url(#loanWash)"
            isAnimationActive={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: colors.surface }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function LoanView({ summary, onSaveSettings, onAddOffer, onDeleteOffer, busy, themeKey }) {
  const { totals, outstanding, available, utilisation, settings, warnings, spread, affordability, comparison, payoff } =
    summary;
  const pct = utilisation === null ? null : Math.min(Math.max(utilisation, 0), 1);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <div className="card flex flex-col justify-center p-5">
          <p className="label mb-1">Outstanding</p>
          <p
            className="text-5xl font-semibold tracking-tight"
            style={{ color: outstanding > 0 ? 'var(--color-s2)' : undefined }}
          >
            {money(outstanding)}
          </p>
          <p className="mt-2 text-sm text-[var(--color-ink-2)]">
            {money(totals.drawn)} drawn · {money(totals.repaid)} repaid
          </p>
          <p className="mt-1 text-xs text-[var(--color-muted)]">
            drawn + interest charged − repaid
          </p>

          {pct !== null ? (
            <div className="mt-4">
              <div className="mb-1 flex items-baseline justify-between text-xs">
                <span className="text-[var(--color-muted)]">Limit used</span>
                <span className="font-semibold tabular-nums">{(utilisation * 100).toFixed(1)}%</span>
              </div>
              <div className="h-2.5 w-full rounded-sm bg-[var(--color-raised)]">
                <div
                  className="h-full rounded-sm"
                  style={{
                    width: `${pct * 100}%`,
                    backgroundColor: utilisation > 0.9 ? 'var(--color-critical)' : 'var(--color-s2)',
                  }}
                />
              </div>
            </div>
          ) : null}

          <div className="mt-4">
            <FacilitySettings settings={settings} onSave={onSaveSettings} busy={busy} />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
          <StatTile
            label="Sanctioned limit"
            value={settings.limit === null ? '—' : money(settings.limit)}
            note={settings.rate !== null ? `${settings.rate}% p.a.` : 'Rate not set'}
          />
          <StatTile
            label="Available to draw"
            value={available === null ? '—' : money(available)}
            note="Limit less outstanding"
            accent={available !== null && available < 0 ? 'var(--color-critical)' : undefined}
          />
          <StatTile label="Total repaid" value={money(totals.repaid)} note="Paid back so far" />
          <StatTile
            label="Interest charged"
            value={money(totals.interestCharged)}
            note="Cost of the loan"
            accent={totals.interestCharged > 0 ? 'var(--color-critical)' : undefined}
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

      {/* Comparator and calculator come first: they are used before borrowing,
          while everything below reports on a loan already taken. */}
      <LoanComparator
        comparison={comparison}
        onAdd={onAddOffer}
        onDelete={onDeleteOffer}
        busy={busy}
        defaultRate={settings.rate}
      />

      <LoanCalculator
        defaultRate={settings.rate}
        affordablePerMonth={affordability?.earningsPerMonth}
      />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <section className="card p-4">
          <div className="mb-3">
            <h2 className="text-sm font-semibold">Outstanding over time</h2>
            <p className="text-xs text-[var(--color-muted)]">Balance after each entry</p>
          </div>
          <BalanceChart data={summary.history} themeKey={themeKey} />
        </section>

        <SpreadCard spread={spread} />
      </div>

      {affordability ? (
        <AffordabilityCard afford={affordability} rate={settings.rate} />
      ) : null}

      {payoff ? (
        <PayoffPlan
          payoff={payoff}
          title="Clearing what you owe"
          affordablePerMonth={affordability?.earningsPerMonth}
        />
      ) : null}

      <RepaymentSchedule
        outstanding={outstanding}
        suggested={affordability?.earningsPerMonth ?? 0}
        rate={settings.rate}
      />
    </div>
  );
}

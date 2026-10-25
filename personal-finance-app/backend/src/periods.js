import { round2 } from './validate.js';

export const GRAINS = ['day', 'week', 'month', 'year'];

const MS_PER_DAY = 86_400_000;

function toUTC(iso) {
  return new Date(`${iso}T00:00:00Z`);
}

const isoOf = (d) => d.toISOString().slice(0, 10);

/** Monday of the week containing `iso`. */
function startOfWeek(iso) {
  const d = toUTC(iso);
  const offset = (d.getUTCDay() + 6) % 7; // Monday = 0
  d.setUTCDate(d.getUTCDate() - offset);
  return isoOf(d);
}

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

/** How many whole periods of this grain span the two dates, inclusive of both ends. */
function countPeriods(from, to, grain) {
  if (to < from) return 1;
  const a = toUTC(from);
  const b = toUTC(to);

  if (grain === 'year') return b.getUTCFullYear() - a.getUTCFullYear() + 1;
  if (grain === 'month') {
    return (b.getUTCFullYear() - a.getUTCFullYear()) * 12 + (b.getUTCMonth() - a.getUTCMonth()) + 1;
  }
  const days = Math.round((b - a) / MS_PER_DAY);
  if (grain === 'week') return Math.floor(days / 7) + 1;
  return days + 1;
}

function bucketKey(iso, grain) {
  if (grain === 'day') return iso;
  if (grain === 'week') return startOfWeek(iso);
  if (grain === 'year') return iso.slice(0, 4);
  return iso.slice(0, 7);
}

/** Inclusive last date covered by a bucket, so the UI can render a range. */
function bucketEnd(key, grain) {
  if (grain === 'day') return key;
  if (grain === 'week') return isoOf(new Date(toUTC(key).getTime() + 6 * MS_PER_DAY));
  if (grain === 'year') return `${key}-12-31`;
  const [y, m] = key.split('-').map(Number);
  return isoOf(new Date(Date.UTC(y, m, 0)));
}

function emptyBucket(key, grain) {
  return {
    key,
    grain,
    start: grain === 'year' ? `${key}-01-01` : grain === 'month' ? `${key}-01` : key,
    end: bucketEnd(key, grain),
    interest: 0,
    principalReceived: 0,
    payoutsReceived: 0,
    payoutCount: 0,
    deposited: 0,
    withdrawn: 0,
    reinvested: 0,
  };
}

/**
 * Groups the ledger into day/week/month/year buckets. Only periods with activity
 * appear — a day grain over a long history would otherwise be mostly empty rows.
 * Closing value is the running portfolio value at the end of each period.
 */
export function buildPeriods(rows, grain = 'month') {
  const useGrain = GRAINS.includes(grain) ? grain : 'month';
  const ordered = [...rows].sort((a, b) => a.date.localeCompare(b.date) || a.id - b.id);

  const buckets = new Map();
  for (const t of ordered) {
    const key = bucketKey(t.date, useGrain);
    if (!buckets.has(key)) buckets.set(key, emptyBucket(key, useGrain));
    const b = buckets.get(key);

    if (t.type === 'deposit') b.deposited += t.amount;
    else if (t.type === 'withdrawal') b.withdrawn += t.amount;
    else if (t.type === 'reinvest') b.reinvested += t.amount;
    else if (t.type === 'payout') {
      b.payoutsReceived += t.amount;
      b.principalReceived += t.principal_portion ?? 0;
      b.interest += t.interest_portion ?? 0;
      b.payoutCount += 1;
    }
  }

  // Annualising factor per grain, for turning a period return into a comparable rate.
  const perYear = { day: 365, week: 52.1775, month: 12, year: 1 }[useGrain];

  const cum = { deposited: 0, interest: 0, withdrawn: 0 };
  const periods = [...buckets.keys()]
    .sort()
    .map((key) => {
      const b = buckets.get(key);
      const openingValue = cum.deposited + cum.interest - cum.withdrawn;

      cum.deposited += b.deposited;
      cum.interest += b.interest;
      cum.withdrawn += b.withdrawn;

      const closingValue = cum.deposited + cum.interest - cum.withdrawn;

      /*
       * Return is measured against the capital that was actually working during the
       * period — the closing value less what it earned, which equals the opening
       * value plus any money moved in or out. Using the opening value alone would
       * make the very first period undefined, since it opens at zero.
       */
      const capitalBase = closingValue - b.interest;
      const returnPct = capitalBase > 0 ? (b.interest / capitalBase) * 100 : null;

      return {
        ...b,
        interest: round2(b.interest),
        principalReceived: round2(b.principalReceived),
        payoutsReceived: round2(b.payoutsReceived),
        deposited: round2(b.deposited),
        withdrawn: round2(b.withdrawn),
        reinvested: round2(b.reinvested),
        netFlow: round2(b.deposited - b.withdrawn),
        openingValue: round2(openingValue),
        closingValue: round2(closingValue),
        capitalBase: round2(capitalBase),
        returnPct: returnPct === null ? null : round2(returnPct),
        annualisedPct: returnPct === null ? null : round2(returnPct * perYear),
      };
    });

  const totalInterest = periods.reduce((sum, p) => sum + p.interest, 0);
  const earning = periods.filter((p) => p.interest > 0);

  /*
   * Elapsed periods from the first with activity through today, counting the quiet
   * ones. LenDen pays at irregular intervals, so months with no payout are normal —
   * averaging over earning months only would overstate income, in some cases by
   * double, and anything built on it (affordability, yield, spread) with it.
   */
  const asOf = todayISO();
  const firstStart = periods.length > 0 ? periods[0].start : asOf;
  const elapsedPeriods = Math.max(countPeriods(firstStart, asOf, useGrain), periods.length, 1);
  const best = earning.reduce(
    (top, p) => (top === null || p.interest > top.interest ? p : top),
    null,
  );

  return {
    grain: useGrain,
    periods,
    totals: {
      interest: round2(totalInterest),
      deposited: round2(periods.reduce((s, p) => s + p.deposited, 0)),
      withdrawn: round2(periods.reduce((s, p) => s + p.withdrawn, 0)),
      payoutCount: periods.reduce((s, p) => s + p.payoutCount, 0),
    },
    best: best ? { key: best.key, start: best.start, end: best.end, interest: best.interest } : null,
    // Average across periods that earned — what the period card reports.
    averageInterest: earning.length > 0 ? round2(totalInterest / earning.length) : 0,
    // Average across every elapsed period, quiet ones included. This is the honest
    // run-rate and the one affordability, yield and the spread must be built on.
    averagePerElapsed: round2(totalInterest / elapsedPeriods),
    elapsedPeriods,
    earningPeriodCount: earning.length,
    periodCount: periods.length,
  };
}

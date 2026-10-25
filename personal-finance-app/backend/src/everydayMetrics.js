import * as repo from './expenseRepository.js';
import { round2 } from './validate.js';

function todayISO() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function startOfWeek(iso) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); // Monday
  return d.toISOString().slice(0, 10);
}

/**
 * Day-by-day money log: income and spending in one stream, newest first, with a
 * running balance. The balance is a cumulative net of logged entries, not a bank
 * balance — it starts at zero on the first entry.
 */
export function buildEverydaySummary({ month, limitDays = 60 } = {}) {
  const all = repo.listExpenses({ month, sort: 'date', dir: 'asc' });
  const today = todayISO();
  const weekStart = startOfWeek(today);
  const monthPrefix = today.slice(0, 7);

  const totals = {
    todayIn: 0,
    todayOut: 0,
    weekIn: 0,
    weekOut: 0,
    monthIn: 0,
    monthOut: 0,
    allIn: 0,
    allOut: 0,
  };

  const byDate = new Map();
  let running = 0;

  for (const e of all) {
    const isIn = e.direction === 'in';
    const signed = isIn ? e.amount : -e.amount;
    running += signed;

    if (isIn) totals.allIn += e.amount;
    else totals.allOut += e.amount;

    if (e.date === today) {
      if (isIn) totals.todayIn += e.amount;
      else totals.todayOut += e.amount;
    }
    if (e.date >= weekStart && e.date <= today) {
      if (isIn) totals.weekIn += e.amount;
      else totals.weekOut += e.amount;
    }
    if (e.date.startsWith(monthPrefix)) {
      if (isIn) totals.monthIn += e.amount;
      else totals.monthOut += e.amount;
    }

    if (!byDate.has(e.date)) byDate.set(e.date, { date: e.date, in: 0, out: 0, entries: [] });
    const day = byDate.get(e.date);
    if (isIn) day.in += e.amount;
    else day.out += e.amount;
    day.entries.push(e);
    day.closing = round2(running);
  }

  const days = [...byDate.values()]
    .map((d) => ({
      ...d,
      in: round2(d.in),
      out: round2(d.out),
      net: round2(d.in - d.out),
      entries: d.entries.slice().reverse(),
    }))
    .reverse()
    .slice(0, limitDays);

  const net = (a, b) => round2(a - b);

  // "Highest spent" over the month in view: by category, and by single entry.
  const scope = all.filter((e) => e.direction === 'out' && e.date.startsWith(month ?? monthPrefix));
  const scopeTotal = scope.reduce((sum, e) => sum + e.amount, 0);

  const catTotals = new Map();
  for (const e of scope) catTotals.set(e.category, (catTotals.get(e.category) ?? 0) + e.amount);

  const topCategories = [...catTotals.entries()]
    .map(([category, amount]) => ({
      key: category,
      label: category,
      amount: round2(amount),
      share: scopeTotal > 0 ? amount / scopeTotal : 0,
    }))
    .sort((a, b) => b.amount - a.amount);

  const topEntries = scope
    .slice()
    .sort((a, b) => b.amount - a.amount)
    .slice(0, 10)
    .map((e) => ({
      key: String(e.id),
      label: e.note ? `${e.category} — ${e.note}` : e.category,
      date: e.date,
      amount: round2(e.amount),
      share: scopeTotal > 0 ? e.amount / scopeTotal : 0,
    }));

  return {
    today,
    weekStart,
    totals: {
      today: { in: round2(totals.todayIn), out: round2(totals.todayOut), net: net(totals.todayIn, totals.todayOut) },
      week: { in: round2(totals.weekIn), out: round2(totals.weekOut), net: net(totals.weekIn, totals.weekOut) },
      month: { in: round2(totals.monthIn), out: round2(totals.monthOut), net: net(totals.monthIn, totals.monthOut) },
      all: { in: round2(totals.allIn), out: round2(totals.allOut), net: net(totals.allIn, totals.allOut) },
    },
    savingsRate:
      totals.monthIn > 0 ? round2(((totals.monthIn - totals.monthOut) / totals.monthIn) * 100) : null,
    runningBalance: round2(running),
    highestSpend: {
      month: month ?? monthPrefix,
      total: round2(scopeTotal),
      byCategory: topCategories,
      byEntry: topEntries,
    },
    days,
    entries: all.slice().reverse(),
    entryCount: all.length,
    incomeCategories: repo.usedCategories('in'),
    expenseCategories: repo.usedCategories('out'),
  };
}

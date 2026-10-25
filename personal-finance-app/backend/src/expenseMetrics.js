import * as repo from './expenseRepository.js';
import { DERIVED_CATEGORY, round2 } from './validate.js';

function currentMonth() {
  const d = new Date();
  const offset = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - offset).toISOString().slice(0, 7);
}

/**
 * Spending for one month: hand-logged expenses by category, plus an "Invested"
 * row derived from the portfolio ledger's deposits so monthly outflow reconciles.
 */
export function buildSpendingSummary(month = currentMonth()) {
  // Spending is the outflow view; income lives on the Everyday tab.
  const expenses = repo.listExpenses({ month, direction: 'out', sort: 'date', dir: 'asc' });
  const invested = round2(repo.depositsForMonth(month));

  const totals = new Map();
  for (const e of expenses) {
    totals.set(e.category, (totals.get(e.category) ?? 0) + e.amount);
  }

  const spent = round2([...totals.values()].reduce((sum, n) => sum + n, 0));
  const totalOut = round2(spent + invested);

  const byCategory = [...totals.entries()]
    .map(([category, amount]) => ({ category, amount: round2(amount), derived: false }))
    .concat(invested > 0 ? [{ category: DERIVED_CATEGORY, amount: invested, derived: true }] : [])
    .map((row) => ({ ...row, share: totalOut > 0 ? row.amount / totalOut : 0 }))
    .sort((a, b) => b.amount - a.amount);

  return {
    month,
    spent,
    invested,
    totalOut,
    entryCount: expenses.length,
    byCategory,
    dailyTotals: buildDailySeries(expenses, month),
    months: repo.activeMonths(),
    knownCategories: repo.usedCategories(),
  };
}

/** Cumulative spend through the month — shows pace, not just the final total. */
function buildDailySeries(expenses, month) {
  if (expenses.length === 0) return [];

  const perDay = new Map();
  for (const e of expenses) {
    perDay.set(e.date, (perDay.get(e.date) ?? 0) + e.amount);
  }

  const [year, mon] = month.split('-').map(Number);
  const daysInMonth = new Date(Date.UTC(year, mon, 0)).getUTCDate();

  const series = [];
  let running = 0;
  for (let day = 1; day <= daysInMonth; day += 1) {
    const date = `${month}-${String(day).padStart(2, '0')}`;
    running += perDay.get(date) ?? 0;
    series.push({ date, day, spent: round2(perDay.get(date) ?? 0), cumulative: round2(running) });
  }
  return series;
}

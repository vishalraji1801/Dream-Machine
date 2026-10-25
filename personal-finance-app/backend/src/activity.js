import { db } from './db.js';

const insertStmt = db.prepare(
  'INSERT INTO activity_log (area, action, detail) VALUES (@area, @action, @detail)',
);

export function record({ area, action, detail = null }) {
  try {
    insertStmt.run({ area, action, detail });
  } catch {
    // Usage tracking must never be able to break the thing it is tracking.
  }
}

/**
 * Every feature the app offers, so "what am I not using" is answerable. Without
 * this registry analytics could only report what *has* been used, which is the
 * less interesting half of the question.
 */
export const FEATURES = [
  { key: 'everyday.log', area: 'everyday', label: 'Logging daily money in/out', tab: 'Everyday' },
  { key: 'everyday.income', area: 'everyday', label: 'Recording income', tab: 'Everyday' },
  { key: 'spending.categories', area: 'spending', label: 'Monthly category breakdown', tab: 'Spending' },
  { key: 'spending.months', area: 'spending', label: 'Browsing other months', tab: 'Spending' },
  { key: 'lenden.transactions', area: 'lenden', label: 'Logging LenDen transactions', tab: 'LenDen' },
  { key: 'lenden.periods', area: 'lenden', label: 'Earnings by period (day/week/month/year)', tab: 'LenDen' },
  { key: 'lenden.projection', area: 'lenden', label: 'Portfolio projection', tab: 'LenDen' },
  { key: 'lenden.npa', area: 'lenden', label: 'Non-performing total', tab: 'LenDen' },
  { key: 'loan.entries', area: 'loan', label: 'Logging loan drawdowns/repayments', tab: 'Loan' },
  { key: 'loan.comparator', area: 'loan', label: 'Comparing lender quotes', tab: 'Loan' },
  { key: 'loan.calculator', area: 'loan', label: 'Loan calculator', tab: 'Loan' },
  { key: 'loan.payoff', area: 'loan', label: 'Payoff planning', tab: 'Loan' },
  { key: 'data.export', area: 'data', label: 'CSV export (backups)', tab: 'Any' },
  { key: 'data.import', area: 'data', label: 'CSV import', tab: 'Any' },
  { key: 'security.lock', area: 'security', label: 'Locking the app', tab: 'Any' },
];

function daysAgoISO(n) {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
}

export function buildAnalytics({ days = 30 } = {}) {
  const since = daysAgoISO(days);

  const total = db.prepare('SELECT COUNT(*) AS n FROM activity_log').get().n;
  const first = db.prepare('SELECT MIN(ts) AS t FROM activity_log').get().t;

  const byAction = db
    .prepare(`
      SELECT area, action, COUNT(*) AS count, MAX(ts) AS lastUsed
        FROM activity_log
       GROUP BY area, action
       ORDER BY count DESC
    `)
    .all();

  const byArea = db
    .prepare('SELECT area, COUNT(*) AS count FROM activity_log GROUP BY area ORDER BY count DESC')
    .all();

  const daily = db
    .prepare(`
      SELECT substr(ts, 1, 10) AS date, COUNT(*) AS count
        FROM activity_log
       WHERE substr(ts, 1, 10) >= ?
       GROUP BY date
       ORDER BY date ASC
    `)
    .all(since);

  const tabViews = db
    .prepare(`
      SELECT detail AS tab, COUNT(*) AS count, MAX(ts) AS lastUsed
        FROM activity_log
       WHERE area = 'navigation' AND action = 'view-tab' AND detail IS NOT NULL
       GROUP BY detail
       ORDER BY count DESC
    `)
    .all();

  // Match each known feature against what has actually been recorded.
  const usedKeys = new Map(byAction.map((r) => [`${r.area}.${r.action}`, r]));
  const features = FEATURES.map((f) => {
    const hit = usedKeys.get(f.key);
    return {
      ...f,
      count: hit?.count ?? 0,
      lastUsed: hit?.lastUsed ?? null,
      used: Boolean(hit),
    };
  });

  return {
    total,
    since,
    trackingSince: first,
    days,
    byAction: byAction.slice(0, 25),
    byArea,
    daily,
    tabViews,
    features: features.sort((a, b) => b.count - a.count),
    unused: features.filter((f) => !f.used),
    usedCount: features.filter((f) => f.used).length,
    featureCount: features.length,
  };
}

export function clearActivity() {
  db.prepare('DELETE FROM activity_log').run();
}

import { round2 } from './validate.js';
import { xirr } from './xirr.js';

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

export function buildSummary(rows, asOf = todayISO(), npa = { amount: 0, updatedAt: null }) {
  const totals = {
    deposited: 0,
    payoutsReceived: 0,
    principalReceived: 0,
    interestEarned: 0,
    reinvested: 0,
    withdrawn: 0,
  };

  for (const t of rows) {
    if (t.type === 'deposit') totals.deposited += t.amount;
    else if (t.type === 'reinvest') totals.reinvested += t.amount;
    else if (t.type === 'withdrawal') totals.withdrawn += t.amount;
    else if (t.type === 'payout') {
      totals.payoutsReceived += t.amount;
      totals.principalReceived += t.principal_portion ?? 0;
      totals.interestEarned += t.interest_portion ?? 0;
    }
  }


  // Non-performing loans are capital you are not getting back, so they come off both
  // the headline value and the deployed figure — which keeps deployed + idle = value.
  const npaAmount = Math.max(npa?.amount ?? 0, 0);

  const grossValue = totals.deposited + totals.interestEarned - totals.withdrawn;
  const portfolioValue = grossValue - npaAmount;
  const grossDeployed = totals.deposited + totals.reinvested - totals.principalReceived;
  const deployed = grossDeployed - npaAmount;
  // Idle is the cash sitting in the wallet: everything paid back, less what has been
  // put back to work or taken out. Interest counts — it is spendable cash.
  const idle = totals.payoutsReceived - totals.reinvested - totals.withdrawn;

  const warnings = [];
  if (idle < -0.01) {
    warnings.push(
      'Idle cash is negative: you have reinvested or withdrawn more than LenDen has paid back. Check for a missing payout, or a reinvest/withdrawal entered too high.',
    );
  }
  if (deployed < -0.01) {
    warnings.push(
      'Deployed capital is negative: principal received exceeds deposits plus reinvestments. This usually means loans funded before you started tracking are paying back — the opening balance needs raising.',
    );
  }
  if (npaAmount > grossDeployed + 0.01) {
    warnings.push(
      `Non-performing (${round2(npaAmount)}) exceeds the capital still deployed (${round2(grossDeployed)}). Check the figure — it should be the amount currently stuck in defaulted loans, not everything ever written off.`,
    );
  }

  const lastDate = rows.reduce((max, t) => (t.date > max ? t.date : max), asOf);

  const flows = [];
  for (const t of rows) {
    if (t.type === 'deposit') flows.push({ date: t.date, amount: -t.amount });
    else if (t.type === 'withdrawal') flows.push({ date: t.date, amount: t.amount });
  }
  if (Math.abs(portfolioValue) > 0.01) flows.push({ date: lastDate, amount: portfolioValue });

  const rate = xirr(flows);

  return {
    asOf,
    totals: {
      deposited: round2(totals.deposited),
      payoutsReceived: round2(totals.payoutsReceived),
      principalReceived: round2(totals.principalReceived),
      interestEarned: round2(totals.interestEarned),
      reinvested: round2(totals.reinvested),
      withdrawn: round2(totals.withdrawn),
    },
    portfolioValue: round2(portfolioValue),
    grossValue: round2(grossValue),
    npa: { amount: round2(npaAmount), updatedAt: npa?.updatedAt ?? null },
    allocation: {
      deployed: round2(deployed),
      idle: round2(idle),
      withdrawn: round2(totals.withdrawn),
    },
    xirr: rate === null || !Number.isFinite(rate) ? null : rate,
    warnings,
    transactionCount: rows.length,
    growth: buildGrowthSeries(rows, asOf),
  };
}

/** Cumulative portfolio value at every date that has activity, plus a point for today. */
export function buildGrowthSeries(rows, asOf = todayISO()) {
  if (rows.length === 0) return [];

  const byDate = new Map();
  for (const t of rows) {
    if (!byDate.has(t.date)) {
      byDate.set(t.date, {
        deposited: 0,
        interest: 0,
        withdrawn: 0,
        principal: 0,
        reinvested: 0,
        payouts: 0,
      });
    }
    const bucket = byDate.get(t.date);
    if (t.type === 'deposit') bucket.deposited += t.amount;
    else if (t.type === 'withdrawal') bucket.withdrawn += t.amount;
    else if (t.type === 'reinvest') bucket.reinvested += t.amount;
    else if (t.type === 'payout') {
      bucket.payouts += t.amount;
      bucket.interest += t.interest_portion ?? 0;
      bucket.principal += t.principal_portion ?? 0;
    }
  }

  const cum = { deposited: 0, interest: 0, withdrawn: 0, principal: 0, reinvested: 0, payouts: 0 };
  const series = [];

  for (const date of [...byDate.keys()].sort()) {
    const day = byDate.get(date);
    cum.deposited += day.deposited;
    cum.interest += day.interest;
    cum.withdrawn += day.withdrawn;
    cum.principal += day.principal;
    cum.reinvested += day.reinvested;
    cum.payouts += day.payouts;

    series.push({
      date,
      value: round2(cum.deposited + cum.interest - cum.withdrawn),
      deposited: round2(cum.deposited),
      interest: round2(cum.interest),
      withdrawn: round2(cum.withdrawn),
      deployed: round2(cum.deposited + cum.reinvested - cum.principal),
      idle: round2(cum.payouts - cum.reinvested - cum.withdrawn),
    });
  }

  const last = series[series.length - 1];
  if (last.date < asOf) series.push({ ...last, date: asOf });

  return series;
}

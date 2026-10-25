import { round2 } from './validate.js';

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Overdraft-style credit line against mutual funds. Interest is debited to the
 * facility like any other charge, so:
 *
 *   outstanding = drawn + interest charged − repaid
 *
 * Repayments are a single figure rather than a principal/interest split, because
 * on a credit line you simply pay money in and it reduces the balance.
 */
export function buildLoanSummary(entries, settings, asOf = todayISO()) {
  const totals = { drawn: 0, repaid: 0, interestCharged: 0 };

  for (const e of entries) {
    if (e.type === 'drawdown') totals.drawn += e.amount;
    else if (e.type === 'repayment') totals.repaid += e.amount;
    else if (e.type === 'interest') totals.interestCharged += e.amount;
  }

  const outstanding = totals.drawn + totals.interestCharged - totals.repaid;
  const limit = settings.limit;
  const available = limit === null ? null : round2(limit - outstanding);
  const utilisation = limit && limit > 0 ? outstanding / limit : null;

  const warnings = [];
  if (outstanding < -0.01) {
    warnings.push(
      'Outstanding is negative — you have repaid more than has been drawn plus interest charged. Check for a missing drawdown or an overstated repayment.',
    );
  }
  if (limit !== null && outstanding > limit + 0.01) {
    warnings.push(
      `Outstanding (${round2(outstanding)}) exceeds the sanctioned limit (${round2(limit)}). Check the limit or the entries.`,
    );
  }

  return {
    asOf,
    settings: { limit, rate: settings.rate },
    totals: {
      drawn: round2(totals.drawn),
      repaid: round2(totals.repaid),
      interestCharged: round2(totals.interestCharged),
    },
    outstanding: round2(outstanding),
    available,
    utilisation,
    entryCount: entries.length,
    warnings,
    history: buildHistory(entries, asOf),
  };
}

/** Outstanding balance after every dated entry, plus a point for today. */
function buildHistory(entries, asOf) {
  if (entries.length === 0) return [];

  const ordered = [...entries].sort((a, b) => a.date.localeCompare(b.date) || a.id - b.id);
  const byDate = new Map();
  let running = 0;

  for (const e of ordered) {
    if (e.type === 'drawdown') running += e.amount;
    else if (e.type === 'interest') running += e.amount;
    else if (e.type === 'repayment') running -= e.amount;
    byDate.set(e.date, round2(running));
  }

  const series = [...byDate.entries()].map(([date, outstanding]) => ({ date, outstanding }));
  const last = series[series.length - 1];
  if (last && last.date < asOf) series.push({ date: asOf, outstanding: last.outstanding });
  return series;
}

/**
 * How much loan interest the portfolio can carry in a month before the borrow stops
 * paying for itself. The ceiling is what LenDen actually earns per month, so this is
 * only as good as the months behind it — a single month of history is a guess.
 */
export function buildAffordability(loanSummary, monthlyPeriods) {
  const months = monthlyPeriods.periods.filter((p) => p.interest > 0);
  // Averaged over every elapsed month, not just the ones that paid out.
  const earningsPerMonth = monthlyPeriods.averagePerElapsed;
  const lastMonth = months.length > 0 ? months[months.length - 1] : null;

  const rate = loanSummary.settings.rate;
  const outstanding = Math.max(loanSummary.outstanding, 0);
  const monthlyRate = rate === null ? null : rate / 100 / 12;

  // What the current balance will cost next month at the stated rate.
  const projectedCost = monthlyRate === null ? null : round2(outstanding * monthlyRate);
  const headroom = projectedCost === null ? null : round2(earningsPerMonth - projectedCost);

  // The balance whose monthly interest exactly consumes the monthly earnings.
  const maxBalance =
    monthlyRate === null || monthlyRate === 0 ? null : round2(earningsPerMonth / monthlyRate);

  // The rate at which the current balance would exactly consume them.
  const breakEvenRate =
    outstanding > 0 ? round2(((earningsPerMonth * 12) / outstanding) * 100) : null;

  return {
    earningsPerMonth: round2(earningsPerMonth),
    lastMonth: lastMonth
      ? { key: lastMonth.key, start: lastMonth.start, interest: lastMonth.interest }
      : null,
    monthsObserved: months.length,
    monthsElapsed: monthlyPeriods.elapsedPeriods,
    averageWhenEarning: monthlyPeriods.averageInterest,
    projectedCost,
    headroom,
    maxBalance,
    breakEvenRate,
    outstanding: round2(outstanding),
    affordable: headroom === null ? null : headroom >= 0,
  };
}

/**
 * Monthly IRR of a cash-flow series: index 0 is what you receive, the rest are what
 * you pay. Newton-Raphson with a bisection fallback, same approach as the XIRR used
 * for the portfolio.
 */
function monthlyIrr(flows, guess = 0.01) {
  const npv = (r) => flows.reduce((sum, f, t) => sum + f / (1 + r) ** t, 0);

  let rate = guess;
  for (let i = 0; i < 100; i += 1) {
    const value = npv(rate);
    if (Math.abs(value) < 1e-7) return rate;

    const slope = flows.reduce((sum, f, t) => sum + (-t * f) / (1 + rate) ** (t + 1), 0);
    if (slope === 0 || !Number.isFinite(slope)) break;

    const next = rate - value / slope;
    if (!Number.isFinite(next) || next <= -0.9999) break;
    if (Math.abs(next - rate) < 1e-10) return next;
    rate = next;
  }

  let low = -0.9;
  let high = 5;
  if (npv(low) * npv(high) > 0) return null;
  for (let i = 0; i < 300; i += 1) {
    const mid = (low + high) / 2;
    if (npv(low) * npv(mid) <= 0) high = mid;
    else low = mid;
  }
  return (low + high) / 2;
}

/**
 * APR: the rate that actually makes the deal, once fees are stripped off what you
 * receive. A quote advertising 9.5% with a hefty processing fee has a materially
 * higher APR, which is the number lenders are obliged to disclose precisely because
 * the headline rate can mislead.
 */
function aprFor(offer, monthlyCost) {
  const upfront = (offer.processing_fee ?? 0) + (offer.other_charges ?? 0);
  const received = offer.amount - upfront;
  if (!(received > 0)) return null;

  const monthlyRate = offer.rate / 100 / 12;
  const annualFeeMonthly = (offer.annual_fee ?? 0) / 12;

  const flows = [received];
  for (let m = 1; m <= offer.tenure_months; m += 1) {
    let outgo = monthlyCost + annualFeeMonthly;
    // Interest-only quotes repay the whole principal at the end.
    if (offer.repayment !== 'emi' && m === offer.tenure_months) outgo += offer.amount;
    flows.push(-outgo);
  }

  const r = monthlyIrr(flows, Math.max(monthlyRate, 0.001));
  return r === null || !Number.isFinite(r) ? null : round2(r * 12 * 100);
}

/** Equal monthly instalment that clears principal and interest over `months`. */
function emiFor(principal, monthlyRate, months) {
  if (months <= 0) return 0;
  if (monthlyRate === 0) return principal / months;
  const factor = (1 + monthlyRate) ** months;
  return (principal * monthlyRate * factor) / (factor - 1);
}

/**
 * What different monthly payments cost you in total. Paying faster means a higher
 * instalment but less interest overall, because interest only accrues on what is
 * still outstanding — this lays that trade-off out side by side.
 */
export function buildPayoffScenarios(principal, rate, { horizons = [6, 12, 24, 36, 48, 60] } = {}) {
  if (!(principal > 0) || rate === null || rate === undefined) return null;

  const monthlyRate = rate / 100 / 12;
  const interestOnly = principal * monthlyRate;

  const rows = horizons.map((months) => {
    const payment = emiFor(principal, monthlyRate, months);
    const totalPaid = payment * months;
    return {
      months,
      payment: round2(payment),
      totalInterest: round2(totalPaid - principal),
      totalPaid: round2(totalPaid),
    };
  });

  // The slowest option is the baseline everything else is measured against.
  const baseline = rows[rows.length - 1];

  return {
    principal: round2(principal),
    rate,
    // Interest-only never touches the principal, so the debt never clears.
    interestOnly: {
      payment: round2(interestOnly),
      clears: false,
      costPerYear: round2(interestOnly * 12),
    },
    rows: rows.map((r) => ({
      ...r,
      savedVsSlowest: round2(baseline.totalInterest - r.totalInterest),
      extraPerMonth: round2(r.payment - baseline.payment),
    })),
    baselineMonths: baseline.months,
  };
}

function addMonthsISO(iso, n) {
  const d = new Date(`${iso}T00:00:00Z`);
  const day = d.getUTCDate();
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() + n);
  const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).getUTCDate();
  d.setUTCDate(Math.min(day, last));
  return d.toISOString().slice(0, 10);
}

/**
 * Month-by-month plan for clearing a balance at a chosen payment. Each row splits
 * the payment into interest and principal, which is the part people find surprising:
 * early payments are mostly interest, and only later does the balance really move.
 *
 * A payment at or below the monthly interest never clears the debt, so that case is
 * reported rather than silently looping.
 */
export function buildRepaymentSchedule(principal, rate, payment, { from = todayISO(), maxMonths = 600 } = {}) {
  if (!(principal > 0) || rate === null || rate === undefined) return null;

  const monthlyRate = rate / 100 / 12;
  const interestOnly = principal * monthlyRate;

  if (!(payment > 0)) {
    return { viable: false, reason: 'no-payment', interestOnly: round2(interestOnly), principal: round2(principal), rate };
  }
  if (payment <= interestOnly + 0.001) {
    return {
      viable: false,
      reason: 'below-interest',
      shortfall: round2(interestOnly - payment),
      minimumToClear: round2(interestOnly),
      interestOnly: round2(interestOnly),
      principal: round2(principal),
      rate,
    };
  }

  const rows = [];
  let balance = principal;
  let totalInterest = 0;
  let month = 0;

  while (balance > 0.005 && month < maxMonths) {
    month += 1;
    const interest = balance * monthlyRate;
    const due = balance + interest;
    // The final instalment is only whatever is left.
    const paid = Math.min(payment, due);
    const principalPaid = paid - interest;

    totalInterest += interest;
    balance = due - paid;

    rows.push({
      month,
      date: addMonthsISO(from, month),
      payment: round2(paid),
      interest: round2(interest),
      principal: round2(principalPaid),
      balance: round2(Math.max(balance, 0)),
      interestShare: paid > 0 ? round2((interest / paid) * 100) : 0,
    });
  }

  const totalPaid = rows.reduce((s, r) => s + r.payment, 0);

  return {
    viable: true,
    principal: round2(principal),
    rate,
    payment: round2(payment),
    months: rows.length,
    clearsOn: rows.length ? rows[rows.length - 1].date : from,
    totalInterest: round2(totalInterest),
    totalPaid: round2(totalPaid),
    interestOnly: round2(interestOnly),
    // How much of each early payment is swallowed by interest.
    firstMonthInterestShare: rows.length ? rows[0].interestShare : 0,
    rows,
  };
}

/**
 * Compares lender quotes on like-for-like terms. The headline is total cost —
 * interest plus fees — because a low rate with a fat processing fee can easily
 * cost more than a higher rate without one.
 *
 * Offers may differ in amount and tenure, so cost alone is not comparable between
 * them; the effective annual rate normalises for both.
 */
export function buildOfferComparison(offers, affordablePerMonth = null) {
  const rows = offers.map((o) => {
    const monthlyRate = o.rate / 100 / 12;

    const monthlyCost =
      o.repayment === 'emi'
        ? emiFor(o.amount, monthlyRate, o.tenure_months)
        : o.amount * monthlyRate;

    const totalInterest =
      o.repayment === 'emi'
        ? monthlyCost * o.tenure_months - o.amount
        : monthlyCost * o.tenure_months;

    const years = o.tenure_months / 12;
    const annualFees = (o.annual_fee ?? 0) * years;
    const upfrontAndRecurring = o.processing_fee + annualFees + (o.other_charges ?? 0);
    const totalCost = totalInterest + upfrontAndRecurring;

    /*
     * Total cost alone cannot compare an EMI loan against an interest-only one: EMI
     * repays principal as it goes, so you have the use of less money. Measuring cost
     * against rupee-months of credit actually used puts them on the same footing —
     * otherwise an EMI quote always looks artificially cheap.
     */
    let rupeeMonths;
    if (o.repayment === 'emi') {
      rupeeMonths = 0;
      let balance = o.amount;
      for (let m = 0; m < o.tenure_months && balance > 0; m += 1) {
        rupeeMonths += balance;
        const interest = balance * monthlyRate;
        balance = balance + interest - monthlyCost;
      }
    } else {
      rupeeMonths = o.amount * o.tenure_months;
    }

    const rupeeYears = rupeeMonths / 12;

    return {
      ...o,
      monthlyCost: round2(monthlyCost),
      totalInterest: round2(totalInterest),
      totalCost: round2(totalCost),
      totalPayable: round2(o.amount + totalCost),
      avgOutstanding: o.tenure_months > 0 ? round2(rupeeMonths / o.tenure_months) : null,
      apr: aprFor(o, monthlyCost),
      annualFees: round2(annualFees),
      chargesTotal: round2(upfrontAndRecurring),
      /*
       * Exiting early is where quotes diverge most: a lender with a low rate can
       * punish you for clearing the debt. Modelled at the halfway point, which is
       * when people typically refinance or pay off.
       */
      earlyExit: (() => {
        const atMonth = Math.max(Math.round(o.tenure_months / 2), 1);
        const blocked = atMonth < (o.lock_in_months ?? 0);

        let balanceAtExit = o.amount;
        if (o.repayment === 'emi') {
          let bal = o.amount;
          for (let m = 0; m < atMonth && bal > 0; m += 1) {
            bal = bal + bal * monthlyRate - monthlyCost;
          }
          balanceAtExit = Math.max(bal, 0);
        }

        const charge = (balanceAtExit * (o.foreclosure_pct ?? 0)) / 100;
        const interestPaid =
          o.repayment === 'emi'
            ? monthlyCost * atMonth - (o.amount - balanceAtExit)
            : monthlyCost * atMonth;

        return {
          atMonth,
          blockedByLockIn: blocked,
          lockInMonths: o.lock_in_months ?? 0,
          balanceAtExit: round2(balanceAtExit),
          foreclosureCharge: round2(charge),
          // Everything the loan costs you if you walk away at the halfway mark.
          totalCostIfExit: round2(
            interestPaid + o.processing_fee + (o.annual_fee ?? 0) * (atMonth / 12) + (o.other_charges ?? 0) + charge,
          ),
        };
      })(),
      // Cost per rupee-year of credit actually used — the like-for-like figure.
      effectiveRate: rupeeYears > 0 ? round2((totalCost / rupeeYears) * 100) : null,
      affordable:
        typeof affordablePerMonth === 'number' && affordablePerMonth > 0
          ? monthlyCost <= affordablePerMonth
          : null,
      headroom:
        typeof affordablePerMonth === 'number' && affordablePerMonth > 0
          ? round2(affordablePerMonth - monthlyCost)
          : null,
      payoff: buildPayoffScenarios(o.amount, o.rate),
    };
  });

  const byEffective = [...rows].filter((r) => r.effectiveRate !== null);
  const cheapest = byEffective.length
    ? byEffective.reduce((best, r) => (r.effectiveRate < best.effectiveRate ? r : best))
    : null;
  const lowestMonthly = rows.length
    ? rows.reduce((best, r) => (r.monthlyCost < best.monthlyCost ? r : best))
    : null;

  return {
    offers: rows.map((r) => ({
      ...r,
      isCheapest: cheapest !== null && r.id === cheapest.id,
      isLowestMonthly: lowestMonthly !== null && r.id === lowestMonthly.id,
    })),
    cheapest: cheapest ? { id: cheapest.id, lender: cheapest.lender, effectiveRate: cheapest.effectiveRate } : null,
    lowestMonthly: lowestMonthly
      ? { id: lowestMonthly.id, lender: lowestMonthly.lender, monthlyCost: lowestMonthly.monthlyCost }
      : null,
    affordablePerMonth: typeof affordablePerMonth === 'number' ? round2(affordablePerMonth) : null,
    count: rows.length,
  };
}

export function buildSpread(loanSummary, portfolioSummary, monthlyPeriods = null) {
  const earned = portfolioSummary.totals.interestEarned;
  const charged = loanSummary.totals.interestCharged;
  const net = earned - charged;

  const loanRate = loanSummary.settings.rate;
  const portfolioValue = portfolioSummary.portfolioValue;
  const outstanding = Math.max(loanSummary.outstanding, 0);

  /*
   * Borrowed rupees cannot be told apart from your own once they are invested, so
   * there is no way to measure what "the loan's money" earned. Two honest answers:
   *
   *   1. Compare rates. If LenDen yields more than the loan costs, every borrowed
   *      rupee is accretive — true regardless of how much you borrowed.
   *   2. Attribute proportionally. The borrowed share of capital is credited with
   *      that same share of the interest. An assumption, but a defensible one.
   */
  const avgMonthlyInterest = monthlyPeriods ? monthlyPeriods.averagePerElapsed : null;

  // Observed yield beats XIRR here: it is not distorted by a short history.
  const observedYield =
    avgMonthlyInterest !== null && portfolioValue > 0 && avgMonthlyInterest > 0
      ? round2(((avgMonthlyInterest * 12) / portfolioValue) * 100)
      : null;

  const borrowedShare =
    portfolioValue > 0 && outstanding > 0 ? Math.min(outstanding / portfolioValue, 1) : 0;

  const attributedPerMonth =
    avgMonthlyInterest !== null && borrowedShare > 0 ? avgMonthlyInterest * borrowedShare : null;

  const loanCostPerMonth = loanRate !== null && outstanding > 0 ? (outstanding * loanRate) / 100 / 12 : null;

  const netPerMonth =
    attributedPerMonth !== null && loanCostPerMonth !== null
      ? attributedPerMonth - loanCostPerMonth
      : null;

  return {
    interestEarned: round2(earned),
    interestCharged: round2(charged),
    net: round2(net),
    positive: net >= 0,
    loanRate,
    portfolioRate: observedYield,
    rateSpread: loanRate !== null && observedYield !== null ? round2(observedYield - loanRate) : null,
    attribution:
      borrowedShare > 0
        ? {
            outstanding: round2(outstanding),
            portfolioValue: round2(portfolioValue),
            borrowedShare: round2(borrowedShare * 100),
            avgMonthlyInterest: round2(avgMonthlyInterest ?? 0),
            attributedPerMonth: attributedPerMonth === null ? null : round2(attributedPerMonth),
            loanCostPerMonth: loanCostPerMonth === null ? null : round2(loanCostPerMonth),
            netPerMonth: netPerMonth === null ? null : round2(netPerMonth),
            worthIt: netPerMonth === null ? null : netPerMonth >= 0,
          }
        : null,
  };
}

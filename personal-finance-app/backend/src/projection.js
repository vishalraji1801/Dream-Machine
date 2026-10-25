import { round2 } from './validate.js';

const MAX_MONTHS = 120;

function addMonths(iso, n) {
  const d = new Date(`${iso}T00:00:00Z`);
  const day = d.getUTCDate();
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() + n);
  // Clamp to the last day of the target month (31 Jan + 1 month → 28/29 Feb).
  const lastDay = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).getUTCDate();
  d.setUTCDate(Math.min(day, lastDay));
  return d.toISOString().slice(0, 10);
}

/**
 * Projects the LenDen portfolio forward.
 *
 * The baseline comes from what actually happened: observed yield is the average
 * monthly interest annualised against the current portfolio value. Overrides let
 * you ask "what if" without pretending the answer is a forecast.
 *
 * Compounds monthly, assuming payouts are reinvested — which matches how the
 * portfolio has actually been run.
 */
export function buildProjection(portfolioSummary, monthlyPeriods, overrides = {}, loan = null) {
  const currentValue = portfolioSummary.portfolioValue;
  const asOf = portfolioSummary.asOf;

  const earningMonths = monthlyPeriods.periods.filter((p) => p.interest > 0);
  // Elapsed-month average: quiet months are part of the real run-rate.
  const avgMonthlyInterest = monthlyPeriods.averagePerElapsed;

  // Annualised yield implied by recent earnings against today's position.
  const observedYield =
    currentValue > 0 && avgMonthlyInterest > 0
      ? round2(((avgMonthlyInterest * 12) / currentValue) * 100)
      : null;

  const yieldPct = pickNumber(overrides.yieldPct, observedYield ?? 0);
  const monthlyTopUp = Math.max(pickNumber(overrides.monthlyTopUp, 0), 0);
  const months = clampInt(pickNumber(overrides.months, 12), 1, MAX_MONTHS);
  const reinvest = overrides.reinvest === undefined ? true : Boolean(overrides.reinvest);

  const monthlyRate = yieldPct / 100 / 12;

  // What actually happened, so the forecast can be read against the real track record.
  const history = (portfolioSummary.growth ?? [])
    .filter((p) => p.date < asOf)
    .map((p) => ({ date: p.date, month: null, actual: p.value }));

  /*
   * A loan only enters the picture once one is actually drawn. The balance is held
   * flat — no repayment schedule is assumed — and its interest accrues each month,
   * so the net line shows what the position is worth after clearing the debt.
   */
  const loanOutstanding = loan && loan.outstanding > 0 ? loan.outstanding : 0;
  const loanRate = loan?.settings?.rate ?? null;
  const loanMonthlyRate = loanOutstanding > 0 && loanRate !== null ? loanRate / 100 / 12 : 0;
  const hasLoan = loanOutstanding > 0;

  const series = [];
  let value = currentValue;
  let contributed = currentValue;
  let interestTotal = 0;
  let loanInterestTotal = 0;

  // Today is the join: both lines carry a point here so they meet rather than jump.
  series.push({
    date: asOf,
    month: 0,
    actual: round2(value),
    value: round2(value),
    contributed: round2(contributed),
    interest: 0,
    ...(hasLoan
      ? { loanInterest: 0, loanOwed: round2(loanOutstanding), netValue: round2(value - loanOutstanding) }
      : {}),
  });

  for (let m = 1; m <= months; m += 1) {
    // Compounds monthly: interest is added to the balance, then earns in its turn.
    const base = reinvest ? value : contributed;
    const interest = base * monthlyRate;

    interestTotal += interest;
    value += interest + monthlyTopUp;
    contributed += monthlyTopUp;

    loanInterestTotal += loanOutstanding * loanMonthlyRate;
    const owed = loanOutstanding + loanInterestTotal;

    series.push({
      date: addMonths(asOf, m),
      month: m,
      value: round2(value),
      contributed: round2(contributed),
      interest: round2(interestTotal),
      ...(hasLoan
        ? {
            loanInterest: round2(loanInterestTotal),
            loanOwed: round2(owed),
            netValue: round2(value - owed),
          }
        : {}),
    });
  }

  const final = series[series.length - 1];
  const combined = [...history, ...series];

  return {
    basis: {
      currentValue: round2(currentValue),
      avgMonthlyInterest: round2(avgMonthlyInterest),
      observedYield,
      monthsObserved: earningMonths.length,
      monthsElapsed: monthlyPeriods.elapsedPeriods,
    },
    assumptions: {
      yieldPct: round2(yieldPct),
      monthlyTopUp: round2(monthlyTopUp),
      months,
      reinvest,
      usingDefaults:
        overrides.yieldPct === undefined &&
        overrides.monthlyTopUp === undefined &&
        overrides.reinvest === undefined,
    },
    projected: {
      value: final.value,
      contributed: final.contributed,
      interest: final.interest,
      growth: round2(final.value - currentValue),
    },
    loan: hasLoan
      ? {
          outstanding: round2(loanOutstanding),
          rate: loanRate,
          interestOverHorizon: round2(loanInterestTotal),
          owedAtEnd: final.loanOwed,
          netValue: final.netValue,
          // Does the portfolio out-earn the borrowing over this horizon?
          netGain: round2(final.interest - loanInterestTotal),
          worthIt: final.interest >= loanInterestTotal,
        }
      : null,
    milestones: [3, 6, 12, 24, 60]
      .filter((m) => m <= months)
      .map((m) => ({ month: m, value: series[m].value, interest: series[m].interest })),
    compounding: 'monthly',
    historyPoints: history.length,
    series: combined,
  };
}

function pickNumber(raw, fallback) {
  if (raw === undefined || raw === null || raw === '') return fallback;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}

function clampInt(n, min, max) {
  return Math.min(Math.max(Math.round(n), min), max);
}

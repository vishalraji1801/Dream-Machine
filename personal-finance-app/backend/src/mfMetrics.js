import { round2 } from './validate.js';
import { xirr } from './xirr.js';

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Mutual fund holdings built from purchase and redemption history.
 *
 * Units held and cost basis come from the transactions; current value needs a NAV,
 * which has to be entered by hand since the app has no price feed. A fund without a
 * NAV is reported as unvalued rather than quietly assuming it is worth its cost.
 *
 * Redemptions reduce the cost basis proportionally (average-cost), which is the
 * convention that keeps "invested" meaning money still at work rather than money
 * ever spent.
 */
export function buildMfSummary(rows, navRows, asOf = todayISO()) {
  const navs = new Map(navRows.map((n) => [n.fund, n]));
  const ordered = [...rows].sort((a, b) => a.date.localeCompare(b.date) || a.id - b.id);

  const funds = new Map();
  const totals = { invested: 0, redeemed: 0, fromLenden: 0, fromBank: 0 };

  for (const t of ordered) {
    if (!funds.has(t.fund)) {
      funds.set(t.fund, {
        fund: t.fund,
        units: 0,
        costBasis: 0,
        invested: 0,
        redeemed: 0,
        realisedGain: 0,
        fromLenden: 0,
        transactions: 0,
      });
    }
    const f = funds.get(t.fund);
    f.transactions += 1;

    if (t.type === 'buy') {
      f.units += t.units ?? 0;
      f.costBasis += t.amount;
      f.invested += t.amount;
      totals.invested += t.amount;
      if (t.source === 'lenden') {
        f.fromLenden += t.amount;
        totals.fromLenden += t.amount;
      } else totals.fromBank += t.amount;
    } else {
      const soldUnits = t.units ?? 0;
      // Average cost of the units going out, so what remains keeps its true basis.
      const avgCost = f.units > 0 ? f.costBasis / f.units : 0;
      const costOfSold = soldUnits > 0 ? avgCost * soldUnits : Math.min(f.costBasis, t.amount);

      f.units = Math.max(f.units - soldUnits, 0);
      f.costBasis = Math.max(f.costBasis - costOfSold, 0);
      f.redeemed += t.amount;
      f.realisedGain += t.amount - costOfSold;
      totals.redeemed += t.amount;
    }
  }

  const holdings = [...funds.values()].map((f) => {
    const navEntry = navs.get(f.fund) ?? null;
    const nav = navEntry?.nav ?? null;
    const valued = nav !== null && f.units > 0;
    const currentValue = valued ? f.units * nav : null;
    const unrealisedGain = currentValue === null ? null : currentValue - f.costBasis;

    return {
      fund: f.fund,
      units: Math.round(f.units * 10000) / 10000,
      costBasis: round2(f.costBasis),
      invested: round2(f.invested),
      redeemed: round2(f.redeemed),
      realisedGain: round2(f.realisedGain),
      fromLenden: round2(f.fromLenden),
      transactions: f.transactions,
      nav,
      navAsOf: navEntry?.as_of ?? null,
      currentValue: currentValue === null ? null : round2(currentValue),
      unrealisedGain: unrealisedGain === null ? null : round2(unrealisedGain),
      returnPct:
        unrealisedGain !== null && f.costBasis > 0
          ? round2((unrealisedGain / f.costBasis) * 100)
          : null,
      // A holding with units but no NAV cannot be valued; say so rather than guess.
      needsNav: f.units > 0 && nav === null,
      closed: f.units <= 0.0001,
    };
  });

  const valuedHoldings = holdings.filter((h) => h.currentValue !== null);
  const currentValue = valuedHoldings.reduce((s, h) => s + h.currentValue, 0);
  const valuedCost = valuedHoldings.reduce((s, h) => s + h.costBasis, 0);
  const unvaluedCost = holdings
    .filter((h) => h.needsNav)
    .reduce((s, h) => s + h.costBasis, 0);

  const realisedGain = holdings.reduce((s, h) => s + h.realisedGain, 0);
  const unrealisedGain = currentValue - valuedCost;

  const warnings = [];
  const missing = holdings.filter((h) => h.needsNav);
  if (missing.length > 0) {
    warnings.push(
      `${missing.length} ${missing.length === 1 ? 'fund has' : 'funds have'} units but no NAV recorded (${missing
        .map((h) => h.fund)
        .join(', ')}). Their ${round2(unvaluedCost)} of cost is excluded from the current value until you set one.`,
    );
  }

  // Purchases out, redemptions in, current value as a closing position.
  const flows = [];
  for (const t of ordered) {
    if (t.type === 'buy') flows.push({ date: t.date, amount: -t.amount });
    else flows.push({ date: t.date, amount: t.amount });
  }
  const lastDate = ordered.reduce((max, t) => (t.date > max ? t.date : max), asOf);
  if (currentValue > 0.01) flows.push({ date: lastDate, amount: currentValue });
  const rate = xirr(flows);

  return {
    asOf,
    holdings: holdings.sort((a, b) => (b.currentValue ?? 0) - (a.currentValue ?? 0)),
    totals: {
      invested: round2(totals.invested),
      redeemed: round2(totals.redeemed),
      costBasis: round2(valuedCost + unvaluedCost),
      fromLenden: round2(totals.fromLenden),
      fromBank: round2(totals.fromBank),
    },
    currentValue: round2(currentValue),
    unvaluedCost: round2(unvaluedCost),
    realisedGain: round2(realisedGain),
    unrealisedGain: round2(unrealisedGain),
    totalGain: round2(realisedGain + unrealisedGain),
    returnPct: valuedCost > 0 ? round2((unrealisedGain / valuedCost) * 100) : null,
    // Share of the portfolio funded by LenDen returns rather than fresh bank money.
    lendenShare:
      totals.invested > 0 ? round2((totals.fromLenden / totals.invested) * 100) : null,
    xirr: rate === null || !Number.isFinite(rate) ? null : rate,
    warnings,
    transactionCount: rows.length,
    fundCount: holdings.filter((h) => !h.closed).length,
  };
}

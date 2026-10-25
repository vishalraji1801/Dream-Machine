const MS_PER_DAY = 86_400_000;
const DAYS_PER_YEAR = 365;

function dayOffset(from, to) {
  return (Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / MS_PER_DAY;
}

function xnpv(rate, flows, base) {
  let sum = 0;
  for (const f of flows) {
    sum += f.amount / (1 + rate) ** (dayOffset(base, f.date) / DAYS_PER_YEAR);
  }
  return sum;
}

function dXnpv(rate, flows, base) {
  let sum = 0;
  for (const f of flows) {
    const years = dayOffset(base, f.date) / DAYS_PER_YEAR;
    sum += (-years * f.amount) / (1 + rate) ** (years + 1);
  }
  return sum;
}

/**
 * Annualised money-weighted return for irregularly spaced cash flows.
 * Newton-Raphson, falling back to bisection when the tangent wanders out of the
 * valid domain (rate <= -1 makes the discount factor undefined).
 */
export function xirr(flows, { guess = 0.1, tolerance = 1e-9, maxIterations = 100 } = {}) {
  if (flows.length < 2) return null;
  if (!flows.some((f) => f.amount < 0) || !flows.some((f) => f.amount > 0)) return null;

  const ordered = [...flows].sort((a, b) => a.date.localeCompare(b.date));
  const base = ordered[0].date;
  if (dayOffset(base, ordered[ordered.length - 1].date) <= 0) return null;

  let rate = guess;
  for (let i = 0; i < maxIterations; i += 1) {
    const value = xnpv(rate, ordered, base);
    if (Math.abs(value) < tolerance) return rate;

    const slope = dXnpv(rate, ordered, base);
    if (slope === 0 || !Number.isFinite(slope)) break;

    const next = rate - value / slope;
    if (!Number.isFinite(next) || next <= -1) break;
    if (Math.abs(next - rate) < tolerance) return next;
    rate = next;
  }

  return bisect(ordered, base, tolerance);
}

function bisect(flows, base, tolerance) {
  let low = -0.9999;
  let high = 1;
  let fLow = xnpv(low, flows, base);
  let fHigh = xnpv(high, flows, base);

  // Expand the upper bound until the root is bracketed (very high returns).
  while (fLow * fHigh > 0 && high < 1e6) {
    high *= 2;
    fHigh = xnpv(high, flows, base);
  }
  if (fLow * fHigh > 0) return null;

  for (let i = 0; i < 200; i += 1) {
    const mid = (low + high) / 2;
    const fMid = xnpv(mid, flows, base);
    if (Math.abs(fMid) < tolerance || (high - low) / 2 < tolerance) return mid;
    if (fLow * fMid < 0) {
      high = mid;
      fHigh = fMid;
    } else {
      low = mid;
      fLow = fMid;
    }
  }
  return (low + high) / 2;
}

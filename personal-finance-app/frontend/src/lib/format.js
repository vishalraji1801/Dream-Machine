const inr0 = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
});

const inr2 = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const plain0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });

export const money = (n) => (Number.isFinite(n) ? inr0.format(n) : '—');
export const moneyExact = (n) => (Number.isFinite(n) ? inr2.format(n) : '—');
export const number = (n) => (Number.isFinite(n) ? plain0.format(n) : '—');

/** XIRR beyond ±999% comes from a stub of history, not a real return — don't print it. */
export const XIRR_LIMIT = 9.99;

export function percent(rate, digits = 2) {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return '—';
  if (Math.abs(rate) > XIRR_LIMIT) return '—';
  return `${(rate * 100).toFixed(digits)}%`;
}

export function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

export function shortDate(iso) {
  if (!iso) return '';
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
}

export function todayISO() {
  const d = new Date();
  const offset = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - offset).toISOString().slice(0, 10);
}

/** Axis ticks: compact Indian units so long rupee values don't crowd the plot. */
export function compactMoney(n) {
  if (!Number.isFinite(n)) return '';
  const abs = Math.abs(n);
  const sign = n < 0 ? '-' : '';
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(abs >= 1e8 ? 0 : 1)}Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(abs >= 1e6 ? 0 : 1)}L`;
  if (abs >= 1e3) return `${sign}₹${(abs / 1e3).toFixed(0)}K`;
  return `${sign}₹${abs.toFixed(0)}`;
}

export const TYPE_META = {
  deposit: { label: 'Deposit', hint: 'Money you moved from your bank into LenDen' },
  payout: {
    label: 'Payout',
    hint: 'Money LenDen credited back — principal + interest, exactly as credited',
  },
  reinvest: { label: 'Reinvest', hint: 'Idle cash put back to work inside LenDen' },
  withdrawal: { label: 'Withdrawal', hint: 'Money you moved from LenDen back to your bank' },
};

export const TYPES = Object.keys(TYPE_META);

export const LOAN_TYPE_META = {
  drawdown: {
    label: 'Drawdown',
    hint: 'Money you drew from the facility against your mutual funds',
  },
  repayment: { label: 'Repayment', hint: 'Money you paid back, reducing the outstanding' },
  interest: {
    label: 'Interest charged',
    hint: 'Interest the lender debited — this adds to what you owe',
  },
};

export const LOAN_TYPES = Object.keys(LOAN_TYPE_META);

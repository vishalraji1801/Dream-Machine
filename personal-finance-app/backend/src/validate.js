export const TRANSACTION_TYPES = ['deposit', 'payout', 'reinvest', 'withdrawal'];

// Payout portions are entered by hand, so allow a paisa of rounding slack.
const SPLIT_TOLERANCE = 0.01;

export class ValidationError extends Error {
  constructor(errors) {
    super(errors.join('; '));
    this.name = 'ValidationError';
    this.status = 400;
    this.errors = errors;
  }
}

export function round2(n) {
  return Math.round((n + Number.EPSILON) * 100) / 100;
}

function parseAmount(raw) {
  if (raw === null || raw === undefined || raw === '') return null;
  const n = typeof raw === 'number' ? raw : Number(String(raw).replace(/[,\s₹]/g, ''));
  return Number.isFinite(n) ? n : null;
}

function isValidDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const d = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
}

/**
 * "Invested" is derived from the portfolio ledger's deposits, never typed by hand —
 * accepting it as an expense category would double-count money leaving the bank.
 */
export const DERIVED_CATEGORY = 'Invested';

export const DEFAULT_CATEGORIES = [
  'Food',
  'Groceries',
  'Rent',
  'Transport',
  'Utilities',
  'Shopping',
  'Health',
  'Entertainment',
  'Education',
  'Other',
];

/** Normalises and validates an expense payload, throwing ValidationError on bad input. */
export const DIRECTIONS = ['in', 'out'];

export const INCOME_CATEGORIES = ['Salary', 'Bonus', 'Refund', 'Gift', 'Other income'];

export function validateExpense(input) {
  const errors = [];

  const date = typeof input?.date === 'string' ? input.date.trim() : '';
  if (!isValidDate(date)) errors.push('date must be a real calendar date in YYYY-MM-DD format');

  const rawDirection = typeof input?.direction === 'string' ? input.direction.trim().toLowerCase() : 'out';
  const direction = rawDirection === '' ? 'out' : rawDirection;
  if (!DIRECTIONS.includes(direction)) errors.push("direction must be 'in' or 'out'");

  const amount = parseAmount(input?.amount);
  if (amount === null) errors.push('amount must be a number');
  else if (amount <= 0) errors.push('amount must be greater than 0');

  const category = typeof input?.category === 'string' ? input.category.trim() : '';
  if (!category) errors.push('category is required');
  else if (category.length > 40) errors.push('category must be 40 characters or fewer');
  else if (direction === 'out' && category.toLowerCase() === DERIVED_CATEGORY.toLowerCase()) {
    errors.push(
      `"${DERIVED_CATEGORY}" is filled in automatically from your portfolio deposits — logging it here would count that money twice`,
    );
  }

  const rawNote = input?.note;
  const note = typeof rawNote === 'string' && rawNote.trim() !== '' ? rawNote.trim() : null;
  if (note !== null && note.length > 200) errors.push('note must be 200 characters or fewer');

  if (errors.length) throw new ValidationError(errors);

  return { date, amount: round2(amount), category, note, direction };
}

/** Current total of defaulted / non-performing loans, as reported by LenDen. */
export function validateNpa(input) {
  const errors = [];
  const amount = parseAmount(input?.amount);

  if (input?.amount === null || input?.amount === undefined || input?.amount === '') {
    return { amount: 0 };
  }
  if (amount === null) errors.push('non-performing total must be a number');
  else if (amount < 0) errors.push('non-performing total cannot be negative');

  if (errors.length) throw new ValidationError(errors);
  return { amount: round2(amount) };
}

export const REPAYMENT_TYPES = ['interest', 'emi'];

/** A quote from a lender, for side-by-side comparison. */
export function validateLoanOffer(input) {
  const errors = [];

  const lender = typeof input?.lender === 'string' ? input.lender.trim() : '';
  if (!lender) errors.push('lender name is required');
  else if (lender.length > 60) errors.push('lender name must be 60 characters or fewer');

  const amount = parseAmount(input?.amount);
  if (amount === null) errors.push('amount must be a number');
  else if (amount <= 0) errors.push('amount must be greater than 0');

  const rate = parseAmount(input?.rate);
  if (rate === null) errors.push('interest rate must be a number');
  else if (rate < 0 || rate > 100) errors.push('interest rate must be between 0 and 100');

  const tenure = parseAmount(input?.tenure_months);
  if (tenure === null) errors.push('tenure must be a number of months');
  else if (!Number.isInteger(tenure) || tenure <= 0) errors.push('tenure must be a whole number of months above 0');
  else if (tenure > 600) errors.push('tenure must be 600 months or fewer');

  const fee = parseAmount(input?.processing_fee) ?? 0;
  if (fee < 0) errors.push('processing fee cannot be negative');

  const foreclosure = parseAmount(input?.foreclosure_pct) ?? 0;
  if (foreclosure < 0 || foreclosure > 100) errors.push('foreclosure charge must be between 0 and 100%');

  const lockIn = parseAmount(input?.lock_in_months) ?? 0;
  if (lockIn < 0 || !Number.isInteger(lockIn)) errors.push('lock-in must be a whole number of months');

  const annualFee = parseAmount(input?.annual_fee) ?? 0;
  if (annualFee < 0) errors.push('annual fee cannot be negative');

  const otherCharges = parseAmount(input?.other_charges) ?? 0;
  if (otherCharges < 0) errors.push('other charges cannot be negative');

  const penalRate = parseAmount(input?.penal_rate) ?? 0;
  if (penalRate < 0 || penalRate > 100) errors.push('penal rate must be between 0 and 100%');

  const partPayment = input?.part_payment === undefined ? 1 : Number(Boolean(
    input.part_payment === true || input.part_payment === 1 || input.part_payment === '1' || input.part_payment === 'yes',
  ));

  const rawRepayment = typeof input?.repayment === 'string' ? input.repayment.trim().toLowerCase() : 'interest';
  const repayment = rawRepayment === '' ? 'interest' : rawRepayment;
  if (!REPAYMENT_TYPES.includes(repayment)) errors.push("repayment must be 'interest' or 'emi'");

  const rawNote = input?.note;
  const note = typeof rawNote === 'string' && rawNote.trim() !== '' ? rawNote.trim() : null;
  if (note !== null && note.length > 200) errors.push('note must be 200 characters or fewer');

  if (errors.length) throw new ValidationError(errors);

  return {
    lender,
    amount: round2(amount),
    rate: round2(rate),
    tenure_months: tenure,
    processing_fee: round2(fee),
    foreclosure_pct: round2(foreclosure),
    lock_in_months: lockIn,
    annual_fee: round2(annualFee),
    other_charges: round2(otherCharges),
    penal_rate: round2(penalRate),
    part_payment: partPayment,
    repayment,
    note,
  };
}

export const MF_TYPES = ['buy', 'sell'];
export const MF_SOURCES = ['bank', 'lenden'];

/**
 * A mutual fund purchase or redemption. Units and NAV are optional — if you give
 * two of amount/units/NAV the third is derived, since statements vary in what they
 * show and re-deriving beats making you do the arithmetic.
 */
export function validateMfTransaction(input) {
  const errors = [];

  const date = typeof input?.date === 'string' ? input.date.trim() : '';
  if (!isValidDate(date)) errors.push('date must be a real calendar date in YYYY-MM-DD format');

  const fund = typeof input?.fund === 'string' ? input.fund.trim() : '';
  if (!fund) errors.push('fund name is required');
  else if (fund.length > 80) errors.push('fund name must be 80 characters or fewer');

  const type = typeof input?.type === 'string' ? input.type.trim().toLowerCase() : '';
  if (!MF_TYPES.includes(type)) errors.push(`type must be one of: ${MF_TYPES.join(', ')}`);

  const rawSource = typeof input?.source === 'string' ? input.source.trim().toLowerCase() : 'bank';
  const source = rawSource === '' ? 'bank' : rawSource;
  if (!MF_SOURCES.includes(source)) errors.push("source must be 'bank' or 'lenden'");

  let amount = parseAmount(input?.amount);
  let units = parseAmount(input?.units);
  let nav = parseAmount(input?.nav);

  if (nav !== null && nav <= 0) errors.push('NAV must be greater than 0');
  if (units !== null && units <= 0) errors.push('units must be greater than 0');

  // Fill in whichever of the three was left out.
  if (amount === null && units !== null && nav !== null && nav > 0) amount = units * nav;
  else if (units === null && amount !== null && nav !== null && nav > 0) units = amount / nav;
  else if (nav === null && amount !== null && units !== null && units > 0) nav = amount / units;

  if (amount === null) errors.push('give an amount, or units and NAV to work it out from');
  else if (amount <= 0) errors.push('amount must be greater than 0');

  const rawNote = input?.note;
  const note = typeof rawNote === 'string' && rawNote.trim() !== '' ? rawNote.trim() : null;
  if (note !== null && note.length > 200) errors.push('note must be 200 characters or fewer');

  if (errors.length) throw new ValidationError(errors);

  return {
    date,
    fund,
    type,
    amount: round2(amount),
    units: units === null ? null : Math.round(units * 10000) / 10000,
    nav: nav === null ? null : Math.round(nav * 10000) / 10000,
    source,
    note,
  };
}

export function validateMfNav(input) {
  const errors = [];

  const fund = typeof input?.fund === 'string' ? input.fund.trim() : '';
  if (!fund) errors.push('fund name is required');

  const nav = parseAmount(input?.nav);
  if (nav === null) errors.push('NAV must be a number');
  else if (nav <= 0) errors.push('NAV must be greater than 0');

  const asOf = typeof input?.as_of === 'string' && isValidDate(input.as_of.trim())
    ? input.as_of.trim()
    : new Date().toISOString().slice(0, 10);

  if (errors.length) throw new ValidationError(errors);
  return { fund, nav: Math.round(nav * 10000) / 10000, as_of: asOf };
}

/** A UI event worth recording locally, for the usage analytics. */
export function validateActivity(input) {
  const errors = [];

  const area = typeof input?.area === 'string' ? input.area.trim().slice(0, 40) : '';
  if (!area) errors.push('area is required');

  const action = typeof input?.action === 'string' ? input.action.trim().slice(0, 60) : '';
  if (!action) errors.push('action is required');

  const rawDetail = input?.detail;
  const detail =
    typeof rawDetail === 'string' && rawDetail.trim() !== '' ? rawDetail.trim().slice(0, 120) : null;

  if (errors.length) throw new ValidationError(errors);
  return { area, action, detail };
}

export const LOAN_TYPES = ['drawdown', 'repayment', 'interest'];

/** Normalises and validates a loan ledger entry. */
export function validateLoanEntry(input) {
  const errors = [];

  const date = typeof input?.date === 'string' ? input.date.trim() : '';
  if (!isValidDate(date)) errors.push('date must be a real calendar date in YYYY-MM-DD format');

  const type = typeof input?.type === 'string' ? input.type.trim().toLowerCase() : '';
  if (!LOAN_TYPES.includes(type)) errors.push(`type must be one of: ${LOAN_TYPES.join(', ')}`);

  const amount = parseAmount(input?.amount);
  if (amount === null) errors.push('amount must be a number');
  else if (amount <= 0) errors.push('amount must be greater than 0');

  const rawNote = input?.note;
  const note = typeof rawNote === 'string' && rawNote.trim() !== '' ? rawNote.trim() : null;
  if (note !== null && note.length > 200) errors.push('note must be 200 characters or fewer');

  if (errors.length) throw new ValidationError(errors);

  return { date, type, amount: round2(amount), note };
}

/** Sanctioned limit and annual rate for the credit facility; both optional. */
export function validateLoanSettings(input) {
  const errors = [];

  const limit = parseAmount(input?.limit);
  if (input?.limit !== null && input?.limit !== undefined && input?.limit !== '') {
    if (limit === null) errors.push('sanctioned limit must be a number');
    else if (limit < 0) errors.push('sanctioned limit cannot be negative');
  }

  const rate = parseAmount(input?.rate);
  if (input?.rate !== null && input?.rate !== undefined && input?.rate !== '') {
    if (rate === null) errors.push('interest rate must be a number');
    else if (rate < 0 || rate > 100) errors.push('interest rate must be between 0 and 100');
  }

  if (errors.length) throw new ValidationError(errors);

  return {
    limit: limit === null ? null : round2(limit),
    rate: rate === null ? null : round2(rate),
  };
}

/** Normalises and validates a transaction payload, throwing ValidationError on bad input. */
export function validateTransaction(input) {
  const errors = [];

  const date = typeof input?.date === 'string' ? input.date.trim() : '';
  if (!isValidDate(date)) errors.push('date must be a real calendar date in YYYY-MM-DD format');

  const type = typeof input?.type === 'string' ? input.type.trim().toLowerCase() : '';
  if (!TRANSACTION_TYPES.includes(type)) {
    errors.push(`type must be one of: ${TRANSACTION_TYPES.join(', ')}`);
  }

  const amount = parseAmount(input?.amount);
  if (amount === null) errors.push('amount must be a number');
  else if (amount <= 0) errors.push('amount must be greater than 0');

  let principal = null;
  let interest = null;

  if (type === 'payout') {
    principal = parseAmount(input?.principal_portion);
    interest = parseAmount(input?.interest_portion);

    if (principal === null) errors.push('principal_portion is required for a payout');
    else if (principal < 0) errors.push('principal_portion cannot be negative');

    if (interest === null) errors.push('interest_portion is required for a payout');
    else if (interest < 0) errors.push('interest_portion cannot be negative');

    // LenDen deducts its platform fee before crediting, so the figures on a statement
    // are already net — there is no fee to account for separately.
    if (principal !== null && interest !== null && amount !== null) {
      const expected = principal + interest;
      if (Math.abs(expected - amount) > SPLIT_TOLERANCE) {
        errors.push(
          `principal + interest (${round2(expected)}) must equal the amount credited (${round2(amount)})`,
        );
      }
    }
  }

  if (errors.length) throw new ValidationError(errors);

  return {
    date,
    type,
    amount: round2(amount),
    principal_portion: type === 'payout' ? round2(principal) : null,
    interest_portion: type === 'payout' ? round2(interest) : null,
    fee_portion: null,
  };
}

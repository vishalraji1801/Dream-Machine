import { Router } from 'express';
import { buildAnalytics, clearActivity, record } from './activity.js';
import { csvToRecords, toCsv } from './csv.js';
import { buildSpendingSummary } from './expenseMetrics.js';
import * as expenseRepo from './expenseRepository.js';
import {
  buildAffordability,
  buildLoanSummary,
  buildOfferComparison,
  buildPayoffScenarios,
  buildRepaymentSchedule,
  buildSpread,
} from './loanMetrics.js';
import * as loanRepo from './loanRepository.js';
import { buildSummary } from './metrics.js';
import { buildMfSummary } from './mfMetrics.js';
import * as mfRepo from './mfRepository.js';
import { buildEverydaySummary } from './everydayMetrics.js';
import { buildPeriods } from './periods.js';
import { buildProjection } from './projection.js';
import * as repo from './repository.js';
import {
  DEFAULT_CATEGORIES,
  INCOME_CATEGORIES,
  ValidationError,
  validateExpense,
  validateLoanEntry,
  validateActivity,
  validateLoanOffer,
  validateMfNav,
  validateMfTransaction,
  validateLoanSettings,
  validateNpa,
  validateTransaction,
} from './validate.js';

export const router = Router();

function parseId(raw) {
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

function parseMonth(raw) {
  return typeof raw === 'string' && /^\d{4}-\d{2}$/.test(raw) ? raw : undefined;
}

router.get('/transactions', (req, res) => {
  res.json(repo.listTransactions({ sort: req.query.sort, dir: req.query.dir }));
});

router.post('/transactions', (req, res) => {
  res.status(201).json(repo.createTransaction(validateTransaction(req.body)));
});

router.put('/transactions/:id', (req, res) => {
  const id = parseId(req.params.id);
  if (id === null) return res.status(400).json({ error: 'Invalid transaction id' });

  const updated = repo.updateTransaction(id, validateTransaction(req.body));
  if (!updated) return res.status(404).json({ error: 'Transaction not found' });
  return res.json(updated);
});

router.delete('/transactions/:id', (req, res) => {
  const id = parseId(req.params.id);
  if (id === null) return res.status(400).json({ error: 'Invalid transaction id' });
  if (!repo.deleteTransaction(id)) return res.status(404).json({ error: 'Transaction not found' });
  return res.status(204).end();
});

router.get('/summary', (_req, res) => {
  res.json(buildSummary(repo.listChronological(), undefined, repo.getNpa()));
});

router.put('/npa', (req, res) => {
  res.json(repo.saveNpa(validateNpa(req.body)));
});

router.get('/periods', (req, res) => {
  res.json(buildPeriods(repo.listChronological(), req.query.grain));
});

router.get('/projection', (req, res) => {
  const transactions = repo.listChronological();
  const portfolio = buildSummary(transactions, undefined, repo.getNpa());
  const monthly = buildPeriods(transactions, 'month');
  // The loan only affects the projection once one is actually drawn.
  const loan = buildLoanSummary(loanRepo.listChronological(), loanRepo.getSettings());

  res.json(
    buildProjection(
      portfolio,
      monthly,
      {
        yieldPct: req.query.yield,
        monthlyTopUp: req.query.topup,
        months: req.query.months,
        reinvest: req.query.reinvest === undefined ? undefined : req.query.reinvest !== 'false',
      },
      loan,
    ),
  );
});

router.get('/everyday', (req, res) => {
  const summary = buildEverydaySummary({ month: parseMonth(req.query.month) });
  res.json({ ...summary, defaultIncomeCategories: INCOME_CATEGORIES, defaultExpenseCategories: DEFAULT_CATEGORIES });
});

router.post('/activity', (req, res) => {
  record(validateActivity(req.body));
  res.status(204).end();
});

router.get('/analytics', (req, res) => {
  const days = Number(req.query.days);
  res.json(buildAnalytics({ days: Number.isFinite(days) && days > 0 ? Math.min(days, 365) : 30 }));
});

router.delete('/activity', (_req, res) => {
  clearActivity();
  res.status(204).end();
});

/* ----------------------------------------------------------- mutual funds */

router.get('/mf-transactions', (req, res) => {
  res.json(mfRepo.listTransactions({ sort: req.query.sort, dir: req.query.dir }));
});

router.post('/mf-transactions', (req, res) => {
  res.status(201).json(mfRepo.createTransaction(validateMfTransaction(req.body)));
});

router.put('/mf-transactions/:id', (req, res) => {
  const id = parseId(req.params.id);
  if (id === null) return res.status(400).json({ error: 'Invalid transaction id' });
  const updated = mfRepo.updateTransaction(id, validateMfTransaction(req.body));
  if (!updated) return res.status(404).json({ error: 'Transaction not found' });
  return res.json(updated);
});

router.delete('/mf-transactions/:id', (req, res) => {
  const id = parseId(req.params.id);
  if (id === null) return res.status(400).json({ error: 'Invalid transaction id' });
  if (!mfRepo.deleteTransaction(id)) return res.status(404).json({ error: 'Transaction not found' });
  return res.status(204).end();
});

router.get('/mf-summary', (_req, res) => {
  const summary = buildMfSummary(mfRepo.listChronological(), mfRepo.listNavs());
  res.json({ ...summary, knownFunds: mfRepo.knownFunds() });
});

router.put('/mf-nav', (req, res) => {
  res.json(mfRepo.saveNav(validateMfNav(req.body)));
});

router.get('/export', (_req, res) => {
  const stamp = new Date().toISOString().slice(0, 10);
  res.setHeader('Content-Type', 'text/csv; charset=utf-8');
  res.setHeader('Content-Disposition', `attachment; filename="lenden-transactions-${stamp}.csv"`);
  res.send(toCsv(repo.listChronological()));
});

/* -------------------------------------------------------------------- loan */

const LOAN_CSV_COLUMNS = ['id', 'date', 'type', 'amount', 'note'];

router.get('/loan-entries', (req, res) => {
  res.json(loanRepo.listEntries({ sort: req.query.sort, dir: req.query.dir }));
});

router.post('/loan-entries', (req, res) => {
  res.status(201).json(loanRepo.createEntry(validateLoanEntry(req.body)));
});

router.put('/loan-entries/:id', (req, res) => {
  const id = parseId(req.params.id);
  if (id === null) return res.status(400).json({ error: 'Invalid entry id' });

  const updated = loanRepo.updateEntry(id, validateLoanEntry(req.body));
  if (!updated) return res.status(404).json({ error: 'Entry not found' });
  return res.json(updated);
});

router.delete('/loan-entries/:id', (req, res) => {
  const id = parseId(req.params.id);
  if (id === null) return res.status(400).json({ error: 'Invalid entry id' });
  if (!loanRepo.deleteEntry(id)) return res.status(404).json({ error: 'Entry not found' });
  return res.status(204).end();
});

router.get('/loan-summary', (_req, res) => {
  const transactions = repo.listChronological();
  const summary = buildLoanSummary(loanRepo.listChronological(), loanRepo.getSettings());
  const portfolio = buildSummary(transactions, undefined, repo.getNpa());
  const monthly = buildPeriods(transactions, 'month');

  const affordability = buildAffordability(summary, monthly);

  res.json({
    ...summary,
    spread: buildSpread(summary, portfolio, monthly),
    affordability,
    comparison: buildOfferComparison(loanRepo.listOffers(), affordability.earningsPerMonth),
    payoff: buildPayoffScenarios(summary.outstanding, summary.settings.rate),
  });
});

router.get('/loan-offers', (_req, res) => {
  res.json(loanRepo.listOffers());
});

router.post('/loan-offers', (req, res) => {
  res.status(201).json(loanRepo.createOffer(validateLoanOffer(req.body)));
});

router.put('/loan-offers/:id', (req, res) => {
  const id = parseId(req.params.id);
  if (id === null) return res.status(400).json({ error: 'Invalid offer id' });
  const updated = loanRepo.updateOffer(id, validateLoanOffer(req.body));
  if (!updated) return res.status(404).json({ error: 'Offer not found' });
  return res.json(updated);
});

router.delete('/loan-offers/:id', (req, res) => {
  const id = parseId(req.params.id);
  if (id === null) return res.status(400).json({ error: 'Invalid offer id' });
  if (!loanRepo.deleteOffer(id)) return res.status(404).json({ error: 'Offer not found' });
  return res.status(204).end();
});

router.get('/loan-schedule', (req, res) => {
  const summary = buildLoanSummary(loanRepo.listChronological(), loanRepo.getSettings());
  const requested = Number(req.query.payment);

  // Default to the largest instalment LenDen earnings could cover.
  const transactions = repo.listChronological();
  const monthly = buildPeriods(transactions, 'month');
  const afford = buildAffordability(summary, monthly);
  const payment = Number.isFinite(requested) && requested > 0 ? requested : afford.earningsPerMonth;

  res.json({
    ...(buildRepaymentSchedule(summary.outstanding, summary.settings.rate, payment) ?? { viable: false, reason: 'no-loan' }),
    suggestedPayment: afford.earningsPerMonth,
    outstanding: summary.outstanding,
  });
});

router.put('/loan-settings', (req, res) => {
  res.json(loanRepo.saveSettings(validateLoanSettings(req.body)));
});

router.get('/loan-export', (_req, res) => {
  const stamp = new Date().toISOString().slice(0, 10);
  res.setHeader('Content-Type', 'text/csv; charset=utf-8');
  res.setHeader('Content-Disposition', `attachment; filename="lenden-loan-${stamp}.csv"`);
  res.send(toCsv(loanRepo.listEntries({ sort: 'date', dir: 'asc' }), LOAN_CSV_COLUMNS));
});

router.post('/loan-import', (req, res) => {
  const csv = typeof req.body === 'string' ? req.body : req.body?.csv;
  if (typeof csv !== 'string' || csv.trim() === '') {
    return res.status(400).json({ error: 'No CSV content supplied' });
  }

  const mode = req.body?.mode === 'replace' ? 'replace' : 'append';
  const records = csvToRecords(csv);
  if (records.length === 0) return res.status(400).json({ error: 'CSV contained no data rows' });

  const payloads = [];
  const rowErrors = [];

  records.forEach((record, i) => {
    try {
      payloads.push(validateLoanEntry(record));
    } catch (err) {
      if (!(err instanceof ValidationError)) throw err;
      rowErrors.push({ row: i + 2, errors: err.errors });
    }
  });

  if (rowErrors.length) {
    return res.status(400).json({
      error: `${rowErrors.length} of ${records.length} rows are invalid. Nothing was imported.`,
      rowErrors: rowErrors.slice(0, 20),
    });
  }

  const imported =
    mode === 'replace' ? loanRepo.replaceAll(payloads) : loanRepo.insertMany(payloads);
  return res.json({ imported, mode });
});

/* ---------------------------------------------------------------- expenses */

const EXPENSE_CSV_COLUMNS = ['id', 'date', 'direction', 'category', 'amount', 'note'];

router.get('/expenses', (req, res) => {
  res.json(
    expenseRepo.listExpenses({
      month: parseMonth(req.query.month),
      direction: req.query.direction,
      sort: req.query.sort,
      dir: req.query.dir,
    }),
  );
});

router.post('/expenses', (req, res) => {
  res.status(201).json(expenseRepo.createExpense(validateExpense(req.body)));
});

router.put('/expenses/:id', (req, res) => {
  const id = parseId(req.params.id);
  if (id === null) return res.status(400).json({ error: 'Invalid expense id' });

  const updated = expenseRepo.updateExpense(id, validateExpense(req.body));
  if (!updated) return res.status(404).json({ error: 'Expense not found' });
  return res.json(updated);
});

router.delete('/expenses/:id', (req, res) => {
  const id = parseId(req.params.id);
  if (id === null) return res.status(400).json({ error: 'Invalid expense id' });
  if (!expenseRepo.deleteExpense(id)) return res.status(404).json({ error: 'Expense not found' });
  return res.status(204).end();
});

router.get('/expenses-summary', (req, res) => {
  const summary = buildSpendingSummary(parseMonth(req.query.month));
  res.json({ ...summary, defaultCategories: DEFAULT_CATEGORIES });
});

router.get('/expenses-export', (_req, res) => {
  const stamp = new Date().toISOString().slice(0, 10);
  const rows = expenseRepo.listExpenses({ sort: 'date', dir: 'asc' });
  res.setHeader('Content-Type', 'text/csv; charset=utf-8');
  res.setHeader('Content-Disposition', `attachment; filename="lenden-expenses-${stamp}.csv"`);
  res.send(toCsv(rows, EXPENSE_CSV_COLUMNS));
});

router.post('/expenses-import', (req, res) => {
  const csv = typeof req.body === 'string' ? req.body : req.body?.csv;
  if (typeof csv !== 'string' || csv.trim() === '') {
    return res.status(400).json({ error: 'No CSV content supplied' });
  }

  const mode = req.body?.mode === 'replace' ? 'replace' : 'append';
  const records = csvToRecords(csv);
  if (records.length === 0) return res.status(400).json({ error: 'CSV contained no data rows' });

  const payloads = [];
  const rowErrors = [];

  records.forEach((record, i) => {
    try {
      payloads.push(validateExpense(record));
    } catch (err) {
      if (!(err instanceof ValidationError)) throw err;
      rowErrors.push({ row: i + 2, errors: err.errors });
    }
  });

  if (rowErrors.length) {
    return res.status(400).json({
      error: `${rowErrors.length} of ${records.length} rows are invalid. Nothing was imported.`,
      rowErrors: rowErrors.slice(0, 20),
    });
  }

  const imported =
    mode === 'replace'
      ? expenseRepo.replaceAllExpenses(payloads)
      : expenseRepo.insertManyExpenses(payloads);
  return res.json({ imported, mode });
});

router.post('/import', (req, res) => {
  const csv = typeof req.body === 'string' ? req.body : req.body?.csv;
  if (typeof csv !== 'string' || csv.trim() === '') {
    return res.status(400).json({ error: 'No CSV content supplied' });
  }

  const mode = req.body?.mode === 'replace' ? 'replace' : 'append';
  const records = csvToRecords(csv);
  if (records.length === 0) return res.status(400).json({ error: 'CSV contained no data rows' });

  const payloads = [];
  const rowErrors = [];

  records.forEach((record, i) => {
    try {
      payloads.push(validateTransaction(record));
    } catch (err) {
      if (!(err instanceof ValidationError)) throw err;
      rowErrors.push({ row: i + 2, errors: err.errors });
    }
  });

  if (rowErrors.length) {
    return res.status(400).json({
      error: `${rowErrors.length} of ${records.length} rows are invalid. Nothing was imported.`,
      rowErrors: rowErrors.slice(0, 20),
    });
  }

  const imported = mode === 'replace' ? repo.replaceAll(payloads) : repo.insertMany(payloads);
  return res.json({ imported, mode });
});

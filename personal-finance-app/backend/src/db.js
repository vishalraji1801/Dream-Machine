import Database from 'better-sqlite3';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const dbPath = process.env.LENDEN_DB ?? resolve(here, '../data/lenden.db');

mkdirSync(dirname(dbPath), { recursive: true });

export const db = new Database(dbPath);

db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');
// FULL fsyncs every commit. This is financial data entered by hand and writes are
// rare, so durability beats throughput: with the WAL default (NORMAL) a commit can
// still be sitting in the log when the process dies, and the entry is lost.
db.pragma('synchronous = FULL');

/** Folds the write-ahead log back into the main file so the .db is self-contained. */
export function checkpoint() {
  try {
    db.pragma('wal_checkpoint(TRUNCATE)');
  } catch {
    // A checkpoint failure is never worth taking the app down for.
  }
}

db.exec(`
  CREATE TABLE IF NOT EXISTS transactions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    date              TEXT    NOT NULL,
    type              TEXT    NOT NULL CHECK (type IN ('deposit', 'payout', 'reinvest', 'withdrawal')),
    amount            REAL    NOT NULL CHECK (amount > 0),
    principal_portion REAL,
    interest_portion  REAL,
    fee_portion       REAL,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
  );

  CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions (date);
  CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions (type);

  CREATE TABLE IF NOT EXISTS expenses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT    NOT NULL,
    amount     REAL    NOT NULL CHECK (amount > 0),
    category   TEXT    NOT NULL,
    note       TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
  );

  CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses (date);
  CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses (category);

  CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS loan_entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT    NOT NULL,
    type       TEXT    NOT NULL CHECK (type IN ('drawdown', 'repayment', 'interest')),
    amount     REAL    NOT NULL CHECK (amount > 0),
    note       TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
  );

  CREATE INDEX IF NOT EXISTS idx_loan_entries_date ON loan_entries (date);
  CREATE INDEX IF NOT EXISTS idx_loan_entries_type ON loan_entries (type);

  CREATE TABLE IF NOT EXISTS loan_offers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    lender         TEXT    NOT NULL,
    amount         REAL    NOT NULL CHECK (amount > 0),
    rate           REAL    NOT NULL CHECK (rate >= 0),
    tenure_months  INTEGER NOT NULL CHECK (tenure_months > 0),
    processing_fee REAL    NOT NULL DEFAULT 0 CHECK (processing_fee >= 0),
    repayment      TEXT    NOT NULL DEFAULT 'interest' CHECK (repayment IN ('interest', 'emi')),
    note           TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
  );
`);

/*
 * Databases briefly used a snapshot-based schema (deposit/withdrawal/snapshot with
 * no payout splits). Rebuild those back to the payout/reinvest model: snapshot rows
 * have no equivalent here and are dropped; real bank transfers carry across.
 */
const existingSchema =
  db.prepare("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'transactions'").get()
    ?.sql ?? '';

if (existingSchema && !existingSchema.includes("'payout'")) {
  db.exec(`
    BEGIN;

    CREATE TABLE transactions_restored (
      id                INTEGER PRIMARY KEY AUTOINCREMENT,
      date              TEXT    NOT NULL,
      type              TEXT    NOT NULL CHECK (type IN ('deposit', 'payout', 'reinvest', 'withdrawal')),
      amount            REAL    NOT NULL CHECK (amount > 0),
      principal_portion REAL,
      interest_portion  REAL,
      fee_portion       REAL,
      created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    INSERT INTO transactions_restored (id, date, type, amount, created_at)
      SELECT id, date, type, amount, created_at
        FROM transactions
       WHERE type IN ('deposit', 'withdrawal') AND amount > 0;

    DROP TABLE transactions;
    ALTER TABLE transactions_restored RENAME TO transactions;

    CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions (date);
    CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions (type);

    COMMIT;
  `);
}

/*
 * fee_portion is retired: LenDen deducts its platform fee before crediting, so the
 * principal and interest on a statement are already net and a payout is simply
 * principal + interest. The column is kept (always written NULL) rather than dropped
 * — rebuilding this table is a data-loss risk that buys nothing here.
 */
/*
 * The Everyday tab logs income as well as spending, so entries gained a direction.
 * Existing rows are all outflows. Spending keeps showing only 'out', so its figures
 * are unchanged — the two tabs read the same ledger rather than duplicating it.
 */
/*
 * A quote is more than its headline rate: foreclosure charges, lock-in periods and
 * annual fees routinely decide which lender is actually cheapest.
 */
const offerColumns = db.prepare('PRAGMA table_info(loan_offers)').all();
const addOfferColumn = (name, decl) => {
  if (!offerColumns.some((c) => c.name === name)) {
    db.exec(`ALTER TABLE loan_offers ADD COLUMN ${name} ${decl}`);
  }
};
addOfferColumn('foreclosure_pct', 'REAL NOT NULL DEFAULT 0');
addOfferColumn('lock_in_months', 'INTEGER NOT NULL DEFAULT 0');
addOfferColumn('annual_fee', 'REAL NOT NULL DEFAULT 0');
addOfferColumn('other_charges', 'REAL NOT NULL DEFAULT 0');
addOfferColumn('part_payment', 'INTEGER NOT NULL DEFAULT 1');
addOfferColumn('penal_rate', 'REAL NOT NULL DEFAULT 0');

db.exec(`
  CREATE TABLE IF NOT EXISTS mf_transactions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT    NOT NULL,
    fund       TEXT    NOT NULL,
    type       TEXT    NOT NULL CHECK (type IN ('buy', 'sell')),
    amount     REAL    NOT NULL CHECK (amount > 0),
    units      REAL,
    nav        REAL,
    source     TEXT    NOT NULL DEFAULT 'bank' CHECK (source IN ('bank', 'lenden')),
    note       TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
  );

  CREATE INDEX IF NOT EXISTS idx_mf_date ON mf_transactions (date);
  CREATE INDEX IF NOT EXISTS idx_mf_fund ON mf_transactions (fund);

  /* Latest NAV per fund, entered by hand — there is no price feed. */
  CREATE TABLE IF NOT EXISTS mf_navs (
    fund   TEXT PRIMARY KEY,
    nav    REAL NOT NULL CHECK (nav > 0),
    as_of  TEXT NOT NULL
  );
`);

/* Local, private record of what gets used in the app — never leaves this machine. */
db.exec(`
  CREATE TABLE IF NOT EXISTS activity_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL DEFAULT (datetime('now')),
    area    TEXT NOT NULL,
    action  TEXT NOT NULL,
    detail  TEXT
  );

  CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_log (ts);
  CREATE INDEX IF NOT EXISTS idx_activity_action ON activity_log (area, action);
`);

const expenseColumns = db.prepare('PRAGMA table_info(expenses)').all();
if (!expenseColumns.some((c) => c.name === 'direction')) {
  db.exec("ALTER TABLE expenses ADD COLUMN direction TEXT NOT NULL DEFAULT 'out'");
}

const transactionColumns = db.prepare('PRAGMA table_info(transactions)').all();
if (!transactionColumns.some((c) => c.name === 'fee_portion')) {
  db.exec('ALTER TABLE transactions ADD COLUMN fee_portion REAL');
}

// Fold any historical fee back into interest so principal + interest = amount holds.
db.exec(`
  UPDATE transactions
     SET interest_portion = ROUND(interest_portion - fee_portion, 2),
         fee_portion = NULL
   WHERE type = 'payout' AND fee_portion IS NOT NULL AND fee_portion > 0
`);

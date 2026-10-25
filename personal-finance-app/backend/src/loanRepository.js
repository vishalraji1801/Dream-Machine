import { db } from './db.js';

const SORTABLE = new Set(['date', 'type', 'amount', 'id']);

const insertStmt = db.prepare(`
  INSERT INTO loan_entries (date, type, amount, note)
  VALUES (@date, @type, @amount, @note)
`);

const updateStmt = db.prepare(`
  UPDATE loan_entries
     SET date = @date, type = @type, amount = @amount, note = @note
   WHERE id = @id
`);

const deleteStmt = db.prepare('DELETE FROM loan_entries WHERE id = ?');
const findStmt = db.prepare('SELECT * FROM loan_entries WHERE id = ?');

const getSetting = db.prepare('SELECT value FROM app_settings WHERE key = ?');
const putSetting = db.prepare(`
  INSERT INTO app_settings (key, value) VALUES (@key, @value)
  ON CONFLICT(key) DO UPDATE SET value = excluded.value
`);
const dropSetting = db.prepare('DELETE FROM app_settings WHERE key = ?');

export function listEntries({ sort = 'date', dir = 'desc' } = {}) {
  const column = SORTABLE.has(sort) ? sort : 'date';
  const direction = String(dir).toLowerCase() === 'asc' ? 'ASC' : 'DESC';
  return db
    .prepare(`SELECT * FROM loan_entries ORDER BY ${column} ${direction}, id ${direction}`)
    .all();
}

export function listChronological() {
  return db.prepare('SELECT * FROM loan_entries ORDER BY date ASC, id ASC').all();
}

export function createEntry(payload) {
  const { lastInsertRowid } = insertStmt.run(payload);
  return findStmt.get(lastInsertRowid);
}

export function updateEntry(id, payload) {
  const { changes } = updateStmt.run({ ...payload, id });
  return changes === 0 ? null : findStmt.get(id);
}

export function deleteEntry(id) {
  return deleteStmt.run(id).changes > 0;
}

export function getSettings() {
  const limit = getSetting.get('loan_limit')?.value;
  const rate = getSetting.get('loan_rate')?.value;
  return {
    limit: limit === undefined ? null : Number(limit),
    rate: rate === undefined ? null : Number(rate),
  };
}

export function saveSettings({ limit, rate }) {
  if (limit === null) dropSetting.run('loan_limit');
  else putSetting.run({ key: 'loan_limit', value: String(limit) });

  if (rate === null) dropSetting.run('loan_rate');
  else putSetting.run({ key: 'loan_rate', value: String(rate) });

  return getSettings();
}

/* ------------------------------------------------------------ loan offers */

const insertOfferStmt = db.prepare(`
  INSERT INTO loan_offers (lender, amount, rate, tenure_months, processing_fee, foreclosure_pct,
                           lock_in_months, annual_fee, other_charges, part_payment, penal_rate, repayment, note)
  VALUES (@lender, @amount, @rate, @tenure_months, @processing_fee, @foreclosure_pct,
          @lock_in_months, @annual_fee, @other_charges, @part_payment, @penal_rate, @repayment, @note)
`);

const updateOfferStmt = db.prepare(`
  UPDATE loan_offers
     SET lender = @lender, amount = @amount, rate = @rate, tenure_months = @tenure_months,
         processing_fee = @processing_fee, foreclosure_pct = @foreclosure_pct,
         lock_in_months = @lock_in_months, annual_fee = @annual_fee,
         other_charges = @other_charges, part_payment = @part_payment,
         penal_rate = @penal_rate,
         repayment = @repayment, note = @note
   WHERE id = @id
`);

const findOfferStmt = db.prepare('SELECT * FROM loan_offers WHERE id = ?');

export function listOffers() {
  return db.prepare('SELECT * FROM loan_offers ORDER BY id ASC').all();
}

export function createOffer(payload) {
  const { lastInsertRowid } = insertOfferStmt.run(payload);
  return findOfferStmt.get(lastInsertRowid);
}

export function updateOffer(id, payload) {
  const { changes } = updateOfferStmt.run({ ...payload, id });
  return changes === 0 ? null : findOfferStmt.get(id);
}

export function deleteOffer(id) {
  return db.prepare('DELETE FROM loan_offers WHERE id = ?').run(id).changes > 0;
}

export const insertMany = db.transaction((payloads) => {
  for (const p of payloads) insertStmt.run(p);
  return payloads.length;
});

export const replaceAll = db.transaction((payloads) => {
  db.prepare('DELETE FROM loan_entries').run();
  for (const p of payloads) insertStmt.run(p);
  return payloads.length;
});

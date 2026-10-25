import { db } from './db.js';

const SORTABLE = new Set(['date', 'type', 'amount', 'id']);

const insertStmt = db.prepare(`
  INSERT INTO transactions (date, type, amount, principal_portion, interest_portion, fee_portion)
  VALUES (@date, @type, @amount, @principal_portion, @interest_portion, @fee_portion)
`);

const updateStmt = db.prepare(`
  UPDATE transactions
     SET date = @date,
         type = @type,
         amount = @amount,
         principal_portion = @principal_portion,
         interest_portion = @interest_portion,
         fee_portion = @fee_portion
   WHERE id = @id
`);

const deleteStmt = db.prepare('DELETE FROM transactions WHERE id = ?');
const findStmt = db.prepare('SELECT * FROM transactions WHERE id = ?');

export function listTransactions({ sort = 'date', dir = 'desc' } = {}) {
  const column = SORTABLE.has(sort) ? sort : 'date';
  const direction = String(dir).toLowerCase() === 'asc' ? 'ASC' : 'DESC';
  return db
    .prepare(`SELECT * FROM transactions ORDER BY ${column} ${direction}, id ${direction}`)
    .all();
}

export function listChronological() {
  return db.prepare('SELECT * FROM transactions ORDER BY date ASC, id ASC').all();
}

export function getTransaction(id) {
  return findStmt.get(id);
}

export function createTransaction(payload) {
  const { lastInsertRowid } = insertStmt.run(payload);
  return findStmt.get(lastInsertRowid);
}

export function updateTransaction(id, payload) {
  const { changes } = updateStmt.run({ ...payload, id });
  return changes === 0 ? null : findStmt.get(id);
}

export function deleteTransaction(id) {
  return deleteStmt.run(id).changes > 0;
}

const getSetting = db.prepare('SELECT value FROM app_settings WHERE key = ?');
const putSetting = db.prepare(`
  INSERT INTO app_settings (key, value) VALUES (@key, @value)
  ON CONFLICT(key) DO UPDATE SET value = excluded.value
`);

/** Only the current total is known — LenDen reports no per-loan default detail. */
export function getNpa() {
  const amount = getSetting.get('npa_amount')?.value;
  return {
    amount: amount === undefined ? 0 : Number(amount),
    updatedAt: getSetting.get('npa_updated_at')?.value ?? null,
  };
}

export function saveNpa({ amount }) {
  putSetting.run({ key: 'npa_amount', value: String(amount) });
  putSetting.run({ key: 'npa_updated_at', value: new Date().toISOString() });
  return getNpa();
}

export const replaceAll = db.transaction((payloads) => {
  db.prepare('DELETE FROM transactions').run();
  for (const p of payloads) insertStmt.run(p);
  return payloads.length;
});

export const insertMany = db.transaction((payloads) => {
  for (const p of payloads) insertStmt.run(p);
  return payloads.length;
});

import { db } from './db.js';

const SORTABLE = new Set(['date', 'amount', 'category', 'id']);

const insertStmt = db.prepare(`
  INSERT INTO expenses (date, amount, category, note, direction)
  VALUES (@date, @amount, @category, @note, @direction)
`);

const updateStmt = db.prepare(`
  UPDATE expenses
     SET date = @date, amount = @amount, category = @category, note = @note, direction = @direction
   WHERE id = @id
`);

const deleteStmt = db.prepare('DELETE FROM expenses WHERE id = ?');
const findStmt = db.prepare('SELECT * FROM expenses WHERE id = ?');

/** `month` is a YYYY-MM prefix; omit it for the whole history. */
export function listExpenses({ month, direction, sort = 'date', dir = 'desc' } = {}) {
  const column = SORTABLE.has(sort) ? sort : 'date';
  const order = String(dir).toLowerCase() === 'asc' ? 'ASC' : 'DESC';

  const clauses = [];
  const params = [];
  if (month) {
    clauses.push('date LIKE ?');
    params.push(`${month}-%`);
  }
  if (direction) {
    clauses.push('direction = ?');
    params.push(direction);
  }
  const where = clauses.length ? `WHERE ${clauses.join(' AND ')}` : '';

  return db
    .prepare(`SELECT * FROM expenses ${where} ORDER BY ${column} ${order}, id ${order}`)
    .all(...params);
}

export function getExpense(id) {
  return findStmt.get(id);
}

export function createExpense(payload) {
  const { lastInsertRowid } = insertStmt.run(payload);
  return findStmt.get(lastInsertRowid);
}

export function updateExpense(id, payload) {
  const { changes } = updateStmt.run({ ...payload, id });
  return changes === 0 ? null : findStmt.get(id);
}

export function deleteExpense(id) {
  return deleteStmt.run(id).changes > 0;
}

/** Distinct categories the user has actually used, most-used first. */
export function usedCategories(direction = 'out') {
  return db
    .prepare('SELECT category, COUNT(*) AS n FROM expenses WHERE direction = ? GROUP BY category ORDER BY n DESC')
    .all(direction)
    .map((r) => r.category);
}

/** Every month that has an expense or a portfolio deposit, newest first. */
export function activeMonths() {
  return db
    .prepare(`
      SELECT DISTINCT substr(date, 1, 7) AS month FROM expenses
      UNION
      SELECT DISTINCT substr(date, 1, 7) AS month FROM transactions WHERE type = 'deposit'
      ORDER BY month DESC
    `)
    .all()
    .map((r) => r.month);
}

/** Deposits are money leaving the bank, so they belong in a spending view. */
export function depositsForMonth(month) {
  const where = month ? "AND date LIKE ?" : '';
  const params = month ? [`${month}-%`] : [];
  return db
    .prepare(`SELECT COALESCE(SUM(amount), 0) AS total FROM transactions WHERE type = 'deposit' ${where}`)
    .get(...params).total;
}

export const insertManyExpenses = db.transaction((payloads) => {
  for (const p of payloads) insertStmt.run(p);
  return payloads.length;
});

export const replaceAllExpenses = db.transaction((payloads) => {
  db.prepare('DELETE FROM expenses').run();
  for (const p of payloads) insertStmt.run(p);
  return payloads.length;
});

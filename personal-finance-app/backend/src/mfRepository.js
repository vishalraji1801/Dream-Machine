import { db } from './db.js';

const SORTABLE = new Set(['date', 'fund', 'amount', 'type', 'id']);

const insertStmt = db.prepare(`
  INSERT INTO mf_transactions (date, fund, type, amount, units, nav, source, note)
  VALUES (@date, @fund, @type, @amount, @units, @nav, @source, @note)
`);

const updateStmt = db.prepare(`
  UPDATE mf_transactions
     SET date = @date, fund = @fund, type = @type, amount = @amount,
         units = @units, nav = @nav, source = @source, note = @note
   WHERE id = @id
`);

const findStmt = db.prepare('SELECT * FROM mf_transactions WHERE id = ?');

export function listTransactions({ sort = 'date', dir = 'desc' } = {}) {
  const column = SORTABLE.has(sort) ? sort : 'date';
  const order = String(dir).toLowerCase() === 'asc' ? 'ASC' : 'DESC';
  return db
    .prepare(`SELECT * FROM mf_transactions ORDER BY ${column} ${order}, id ${order}`)
    .all();
}

export function listChronological() {
  return db.prepare('SELECT * FROM mf_transactions ORDER BY date ASC, id ASC').all();
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
  return db.prepare('DELETE FROM mf_transactions WHERE id = ?').run(id).changes > 0;
}

export function listNavs() {
  return db.prepare('SELECT * FROM mf_navs').all();
}

export function saveNav({ fund, nav, as_of }) {
  db.prepare(`
    INSERT INTO mf_navs (fund, nav, as_of) VALUES (@fund, @nav, @as_of)
    ON CONFLICT(fund) DO UPDATE SET nav = excluded.nav, as_of = excluded.as_of
  `).run({ fund, nav, as_of });
  return db.prepare('SELECT * FROM mf_navs WHERE fund = ?').get(fund);
}

/** Fund names already used, so the form can suggest them. */
export function knownFunds() {
  return db
    .prepare('SELECT DISTINCT fund FROM mf_transactions ORDER BY fund')
    .all()
    .map((r) => r.fund);
}

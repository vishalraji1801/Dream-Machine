export const CSV_COLUMNS = [
  'id',
  'date',
  'type',
  'amount',
  'principal_portion',
  'interest_portion',
];

function escapeCell(value) {
  if (value === null || value === undefined) return '';
  const s = String(value);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(rows, columns = CSV_COLUMNS) {
  const lines = [columns.join(',')];
  for (const row of rows) {
    lines.push(columns.map((c) => escapeCell(row[c])).join(','));
  }
  return `${lines.join('\r\n')}\r\n`;
}

/** RFC 4180 style parser: handles quoted cells, embedded commas, newlines and "" escapes. */
export function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let inQuotes = false;
  const input = text.replace(/^﻿/, '');

  for (let i = 0; i < input.length; i += 1) {
    const ch = input[i];

    if (inQuotes) {
      if (ch === '"') {
        if (input[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        cell += ch;
      }
      continue;
    }

    if (ch === '"') inQuotes = true;
    else if (ch === ',') {
      row.push(cell);
      cell = '';
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && input[i + 1] === '\n') i += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else cell += ch;
  }

  if (cell !== '' || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }

  return rows.filter((r) => r.some((c) => c.trim() !== ''));
}

/** Turns CSV text into raw objects keyed by header name. Header order is free-form. */
export function csvToRecords(text) {
  const rows = parseCsv(text);
  if (rows.length === 0) return [];

  const header = rows[0].map((h) => h.trim().toLowerCase().replace(/\s+/g, '_'));
  return rows.slice(1).map((cells) => {
    const record = {};
    header.forEach((key, i) => {
      const value = (cells[i] ?? '').trim();
      record[key] = value === '' ? null : value;
    });
    return record;
  });
}

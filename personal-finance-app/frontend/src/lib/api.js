const BASE = '/api';

// Kept in memory only — never localStorage — so closing the app always re-locks it.
let token = null;

export function setToken(next) {
  token = next;
}

export function hasToken() {
  return token !== null;
}

class ApiError extends Error {
  constructor(message, errors, status) {
    super(message);
    this.errors = errors ?? [message];
    this.status = status;
  }
}

function authHeaders(extra = {}) {
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...options,
      headers: authHeaders(options.body ? { 'Content-Type': 'application/json' } : {}),
    });
  } catch {
    throw new ApiError('Cannot reach the API. Is the app still running?');
  }

  if (res.status === 204) return null;

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;

  if (!res.ok) {
    throw new ApiError(data?.error ?? `Request failed (${res.status})`, data?.errors, res.status);
  }
  return data;
}

/** Downloads come through fetch so they can carry the auth header. */
async function downloadCsv(path, filename) {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() });
  if (!res.ok) throw new ApiError(`Export failed (${res.status})`, null, res.status);

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const stamp = () => new Date().toISOString().slice(0, 10);

export const api = {
  authStatus: () => request('/auth/status'),
  setupPin: (pin) => request('/auth/setup', { method: 'POST', body: JSON.stringify({ pin }) }),
  unlock: (pin) => request('/auth/unlock', { method: 'POST', body: JSON.stringify({ pin }) }),
  lock: () => request('/auth/lock', { method: 'POST' }),
  changePin: (currentPin, newPin) =>
    request('/auth/change', { method: 'POST', body: JSON.stringify({ currentPin, newPin }) }),

  listTransactions: (sort = 'date', dir = 'desc') =>
    request(`/transactions?sort=${sort}&dir=${dir}`),
  createTransaction: (payload) =>
    request('/transactions', { method: 'POST', body: JSON.stringify(payload) }),
  updateTransaction: (id, payload) =>
    request(`/transactions/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteTransaction: (id) => request(`/transactions/${id}`, { method: 'DELETE' }),
  summary: () => request('/summary'),
  periods: (grain) => request(`/periods?grain=${grain}`),
  saveNpa: (payload) => request('/npa', { method: 'PUT', body: JSON.stringify(payload) }),
  projection: (opts) => {
    const q = new URLSearchParams();
    if (opts) {
      if (opts.yieldPct !== undefined) q.set('yield', opts.yieldPct);
      if (opts.monthlyTopUp !== undefined) q.set('topup', opts.monthlyTopUp);
      if (opts.months !== undefined) q.set('months', opts.months);
    }
    const qs = q.toString();
    return request(qs ? '/projection?' + qs : '/projection');
  },
  everyday: () => request('/everyday'),

  listMfTransactions: (sort = 'date', dir = 'desc') => request(`/mf-transactions?sort=${sort}&dir=${dir}`),
  createMfTransaction: (p) => request('/mf-transactions', { method: 'POST', body: JSON.stringify(p) }),
  updateMfTransaction: (id, p) => request(`/mf-transactions/${id}`, { method: 'PUT', body: JSON.stringify(p) }),
  deleteMfTransaction: (id) => request(`/mf-transactions/${id}`, { method: 'DELETE' }),
  mfSummary: () => request('/mf-summary'),
  saveMfNav: (p) => request('/mf-nav', { method: 'PUT', body: JSON.stringify(p) }),
  analytics: (days = 30) => request(`/analytics?days=${days}`),
  logActivity: (area, action, detail) =>
    request('/activity', { method: 'POST', body: JSON.stringify({ area, action, detail }) }).catch(() => {}),
  clearActivity: () => request('/activity', { method: 'DELETE' }),
  importCsv: (csv, mode) => request('/import', { method: 'POST', body: JSON.stringify({ csv, mode }) }),
  exportCsv: () => downloadCsv('/export', `lenden-transactions-${stamp()}.csv`),

  listLoanEntries: (sort = 'date', dir = 'desc') =>
    request(`/loan-entries?sort=${sort}&dir=${dir}`),
  createLoanEntry: (payload) =>
    request('/loan-entries', { method: 'POST', body: JSON.stringify(payload) }),
  updateLoanEntry: (id, payload) =>
    request(`/loan-entries/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteLoanEntry: (id) => request(`/loan-entries/${id}`, { method: 'DELETE' }),
  loanSummary: () => request('/loan-summary'),
  loanSchedule: (payment) => request(payment ? `/loan-schedule?payment=${payment}` : '/loan-schedule'),
  createLoanOffer: (payload) => request('/loan-offers', { method: 'POST', body: JSON.stringify(payload) }),
  deleteLoanOffer: (id) => request(`/loan-offers/${id}`, { method: 'DELETE' }),
  saveLoanSettings: (payload) =>
    request('/loan-settings', { method: 'PUT', body: JSON.stringify(payload) }),
  importLoanCsv: (csv, mode) =>
    request('/loan-import', { method: 'POST', body: JSON.stringify({ csv, mode }) }),
  exportLoanCsv: () => downloadCsv('/loan-export', `lenden-loan-${stamp()}.csv`),

  listExpenses: (month, sort = 'date', dir = 'desc') =>
    request(`/expenses?month=${month}&sort=${sort}&dir=${dir}`),
  createExpense: (payload) =>
    request('/expenses', { method: 'POST', body: JSON.stringify(payload) }),
  updateExpense: (id, payload) =>
    request(`/expenses/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteExpense: (id) => request(`/expenses/${id}`, { method: 'DELETE' }),
  spendingSummary: (month) => request(`/expenses-summary?month=${month}`),
  importExpensesCsv: (csv, mode) =>
    request('/expenses-import', { method: 'POST', body: JSON.stringify({ csv, mode }) }),
  exportExpensesCsv: () => downloadCsv('/expenses-export', `lenden-expenses-${stamp()}.csv`),
};

export { ApiError };

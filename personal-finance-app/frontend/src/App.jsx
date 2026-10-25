import { useCallback, useEffect, useRef, useState } from 'react';
import Dashboard from './components/Dashboard.jsx';
import DataTools from './components/DataTools.jsx';
import ExpenseForm from './components/ExpenseForm.jsx';
import ExpenseTable from './components/ExpenseTable.jsx';
import SpendingView, { monthLabel } from './components/SpendingView.jsx';
import TransactionForm from './components/TransactionForm.jsx';
import TransactionTable from './components/TransactionTable.jsx';
import LoanForm from './components/LoanForm.jsx';
import LoanTable from './components/LoanTable.jsx';
import LoanView from './components/LoanView.jsx';
import EverydayForm from './components/EverydayForm.jsx';
import EverydayTable from './components/EverydayTable.jsx';
import EverydayView from './components/EverydayView.jsx';
import AnalyticsView from './components/AnalyticsView.jsx';
import MfLog from './components/MfLog.jsx';
import MutualFundForm from './components/MutualFundForm.jsx';
import MutualFundView from './components/MutualFundView.jsx';
import LockScreen from './components/LockScreen.jsx';
import { api, setToken } from './lib/api.js';
import { todayISO } from './lib/format.js';

// How long the app sits idle before locking itself again.
const IDLE_LOCK_MS = 5 * 60 * 1000;

const TABS = [
  { key: 'everyday', label: 'Everyday' },
  { key: 'spending', label: 'Spending' },
  { key: 'portfolio', label: 'LenDen' },
  { key: 'loan', label: 'Loan' },
  { key: 'mf', label: 'Mutual Funds' },
  { key: 'analytics', label: 'Analytics' },
];

export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem('lenden-theme') ?? 'system');
  const [tab, setTab] = useState(() => localStorage.getItem('lenden-tab') ?? 'portfolio');

  const [transactions, setTransactions] = useState([]);
  const [summary, setSummary] = useState(null);
  const [sort, setSort] = useState('date');
  const [dir, setDir] = useState('desc');
  const [filter, setFilter] = useState('all');
  const [grain, setGrain] = useState(() => localStorage.getItem('lenden-grain') ?? 'month');
  const [periods, setPeriods] = useState(null);
  const [editing, setEditing] = useState(null);

  const [expenses, setExpenses] = useState([]);
  const [spending, setSpending] = useState(null);
  const [month, setMonth] = useState(() => todayISO().slice(0, 7));
  const [exSort, setExSort] = useState('date');
  const [exDir, setExDir] = useState('desc');
  const [editingExpense, setEditingExpense] = useState(null);

  const [loanEntries, setLoanEntries] = useState([]);
  const [loan, setLoan] = useState(null);
  const [lnSort, setLnSort] = useState('date');
  const [lnDir, setLnDir] = useState('desc');
  const [lnFilter, setLnFilter] = useState('all');
  const [editingLoan, setEditingLoan] = useState(null);

  const [everyday, setEveryday] = useState(null);
  const [editingEveryday, setEditingEveryday] = useState(null);
  const [projection, setProjection] = useState(null);
  const [projOpts, setProjOpts] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [mf, setMf] = useState(null);
  const [mfRows, setMfRows] = useState([]);
  const [editingMf, setEditingMf] = useState(null);

  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [auth, setAuth] = useState(null);
  const [lockoutMs, setLockoutMs] = useState(0);
  const [showPinSetup, setShowPinSetup] = useState(false);
  const formRef = useRef(null);
  const expenseFormRef = useRef(null);
  const loanFormRef = useRef(null);
  const mfFormRef = useRef(null);
  const everydayFormRef = useRef(null);

  const unlocked = auth !== null && (!auth.configured || auth.unlocked);

  useEffect(() => {
    api
      .authStatus()
      .then(setAuth)
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  const lockNow = useCallback(async () => {
    try {
      await api.lock();
    } catch {
      // Locking the UI matters more than the server acknowledging it.
    }
    setToken(null);
    setAuth({ configured: true, unlocked: false, lockoutMs: 0 });
    setSummary(null);
    setPeriods(null);
    setSpending(null);
    setTransactions([]);
    setExpenses([]);
    setEditing(null);
    setEditingExpense(null);
  }, []);

  // Auto-lock on inactivity, so an unattended screen doesn't stay open.
  useEffect(() => {
    if (!unlocked || !auth?.configured) return undefined;

    let timer = window.setTimeout(lockNow, IDLE_LOCK_MS);
    const reset = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(lockNow, IDLE_LOCK_MS);
    };

    const events = ['mousedown', 'keydown', 'wheel', 'touchstart'];
    events.forEach((e) => window.addEventListener(e, reset, { passive: true }));
    return () => {
      window.clearTimeout(timer);
      events.forEach((e) => window.removeEventListener(e, reset));
    };
  }, [unlocked, auth?.configured, lockNow]);

  useEffect(() => {
    if (theme === 'system') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('lenden-theme', theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem('lenden-tab', tab);
    if (unlocked) {
      const label = TABS.find((t) => t.key === tab)?.label ?? tab;
      api.logActivity('navigation', 'view-tab', label);
    }
  }, [tab, unlocked]);

  useEffect(() => {
    localStorage.setItem('lenden-grain', grain);
  }, [grain]);

  const refreshPortfolio = useCallback(async () => {
    const [rows, next, byPeriod, proj] = await Promise.all([
      api.listTransactions(sort, dir),
      api.summary(),
      api.periods(grain),
      api.projection(projOpts),
    ]);
    setTransactions(rows);
    setSummary(next);
    setPeriods(byPeriod);
    setProjection(proj);
  }, [sort, dir, grain, projOpts]);

  const refreshEveryday = useCallback(async () => {
    setEveryday(await api.everyday());
  }, []);

  const refreshAnalytics = useCallback(async () => {
    setAnalytics(await api.analytics());
  }, []);

  const refreshMf = useCallback(async () => {
    const [rows, next] = await Promise.all([api.listMfTransactions(), api.mfSummary()]);
    setMfRows(rows);
    setMf(next);
  }, []);

  const refreshSpending = useCallback(async () => {
    const [rows, next] = await Promise.all([
      api.listExpenses(month, exSort, exDir),
      api.spendingSummary(month),
    ]);
    setExpenses(rows);
    setSpending(next);
  }, [month, exSort, exDir]);

  const refreshLoan = useCallback(async () => {
    const [rows, next] = await Promise.all([api.listLoanEntries(lnSort, lnDir), api.loanSummary()]);
    setLoanEntries(rows);
    setLoan(next);
  }, [lnSort, lnDir]);

  const refreshAll = useCallback(async () => {
    try {
      await Promise.all([refreshPortfolio(), refreshSpending(), refreshLoan(), refreshEveryday(), refreshAnalytics(), refreshMf()]);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [refreshPortfolio, refreshSpending, refreshLoan, refreshEveryday, refreshAnalytics, refreshMf]);

  useEffect(() => {
    if (unlocked) refreshAll();
  }, [refreshAll, unlocked]);

  async function handleUnlock(pin) {
    try {
      const { token } = await api.unlock(pin);
      setToken(token);
      setLoading(true);
      setAuth({ configured: true, unlocked: true, lockoutMs: 0 });
    } catch (err) {
      setLockoutMs(err.lockoutMs ?? 0);
      throw err;
    }
  }

  async function handleSetupPin(pin) {
    const { token } = await api.setupPin(pin);
    setToken(token);
    setLoading(true);
    setAuth({ configured: true, unlocked: true, lockoutMs: 0 });
  }

  useEffect(() => {
    if (!status) return undefined;
    const id = setTimeout(() => setStatus(null), 4000);
    return () => clearTimeout(id);
  }, [status]);

  function toggleSort(key) {
    if (key === sort) setDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSort(key);
      setDir(key === 'date' ? 'desc' : 'asc');
    }
  }

  function toggleExpenseSort(key) {
    if (key === exSort) setExDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setExSort(key);
      setExDir(key === 'date' ? 'desc' : 'asc');
    }
  }

  async function handleSubmit(payload) {
    setBusy(true);
    try {
      if (editing) {
        await api.updateTransaction(editing.id, payload);
        setStatus(`Transaction #${editing.id} updated.`);
        setEditing(null);
      } else {
        await api.createTransaction(payload);
        setStatus('Transaction added.');
      }
      await refreshAll();
    } finally {
      setBusy(false);
    }
  }

  async function handleExpenseSubmit(payload) {
    setBusy(true);
    try {
      if (editingExpense) {
        await api.updateExpense(editingExpense.id, payload);
        setStatus(`Expense #${editingExpense.id} updated.`);
        setEditingExpense(null);
      } else {
        await api.createExpense(payload);
        setStatus('Expense added.');
      }
      await refreshAll();
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(row) {
    if (!window.confirm(`Delete the ${row.type} of ₹${row.amount} on ${row.date}?`)) return;
    setBusy(true);
    try {
      await api.deleteTransaction(row.id);
      if (editing?.id === row.id) setEditing(null);
      setStatus('Transaction deleted.');
      await refreshAll();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleExpenseDelete(row) {
    if (!window.confirm(`Delete the ${row.category} expense of ₹${row.amount} on ${row.date}?`)) return;
    setBusy(true);
    try {
      await api.deleteExpense(row.id);
      if (editingExpense?.id === row.id) setEditingExpense(null);
      setStatus('Expense deleted.');
      await refreshAll();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleLoanSubmit(payload) {
    setBusy(true);
    try {
      if (editingLoan) {
        await api.updateLoanEntry(editingLoan.id, payload);
        setStatus(`Loan entry #${editingLoan.id} updated.`);
        setEditingLoan(null);
      } else {
        await api.createLoanEntry(payload);
        setStatus('Loan entry added.');
      }
      await refreshAll();
    } finally {
      setBusy(false);
    }
  }

  async function handleLoanDelete(row) {
    if (!window.confirm(`Delete the ${row.type} of ₹${row.amount} on ${row.date}?`)) return;
    setBusy(true);
    try {
      await api.deleteLoanEntry(row.id);
      if (editingLoan?.id === row.id) setEditingLoan(null);
      setStatus('Loan entry deleted.');
      await refreshAll();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleEverydaySubmit(payload) {
    setBusy(true);
    try {
      if (editingEveryday) {
        await api.updateExpense(editingEveryday.id, payload);
        setStatus(`Entry #${editingEveryday.id} updated.`);
        setEditingEveryday(null);
      } else {
        await api.createExpense(payload);
        setStatus(payload.direction === 'in' ? 'Income logged.' : 'Expense logged.');
      }
      await refreshAll();
    } finally {
      setBusy(false);
    }
  }

  async function handleEverydayDelete(row) {
    const kind = row.direction === 'in' ? 'income' : 'expense';
    if (!window.confirm(`Delete the ${row.category} ${kind} of ₹${row.amount} on ${row.date}?`)) return;
    setBusy(true);
    try {
      await api.deleteExpense(row.id);
      if (editingEveryday?.id === row.id) setEditingEveryday(null);
      setStatus('Entry deleted.');
      await refreshAll();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleMfSubmit(payload) {
    setBusy(true);
    try {
      if (editingMf) {
        await api.updateMfTransaction(editingMf.id, payload);
        setStatus('Fund entry updated.');
        setEditingMf(null);
      } else {
        await api.createMfTransaction(payload);
        setStatus('Fund transaction added.');
      }
      await refreshAll();
    } finally {
      setBusy(false);
    }
  }

  async function handleMfDelete(row) {
    if (!window.confirm('Delete the ' + row.type + ' of ' + row.fund + ' on ' + row.date + '?')) return;
    setBusy(true);
    try {
      await api.deleteMfTransaction(row.id);
      if (editingMf?.id === row.id) setEditingMf(null);
      setStatus('Fund entry deleted.');
      await refreshAll();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveNav(payload) {
    setBusy(true);
    try {
      await api.saveMfNav(payload);
      setStatus('NAV updated.');
      await refreshAll();
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setBusy(false);
    }
  }

  async function handleClearActivity() {
    if (!window.confirm('Clear the whole usage log? The analytics start again from zero.')) return;
    setBusy(true);
    try {
      await api.clearActivity();
      setStatus('Usage log cleared.');
      await refreshAll();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveNpa(payload) {
    setBusy(true);
    try {
      await api.saveNpa(payload);
      setStatus('Non-performing total updated.');
      await refreshAll();
    } finally {
      setBusy(false);
    }
  }

  async function handleAddOffer(payload) {
    setBusy(true);
    try {
      await api.createLoanOffer(payload);
      setStatus('Quote added.');
      await refreshAll();
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteOffer(row) {
    if (!window.confirm('Delete the quote from ' + row.lender + '?')) return;
    setBusy(true);
    try {
      await api.deleteLoanOffer(row.id);
      setStatus('Quote deleted.');
      await refreshAll();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveLoanSettings(payload) {
    setBusy(true);
    try {
      await api.saveLoanSettings(payload);
      setStatus('Facility details saved.');
      await refreshAll();
    } finally {
      setBusy(false);
    }
  }

  function toggleLoanSort(key) {
    if (key === lnSort) setLnDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setLnSort(key);
      setLnDir(key === 'date' ? 'desc' : 'asc');
    }
  }

  async function handleImported(result) {
    setStatus(`Imported ${result.imported} rows (${result.mode}).`);
    setEditing(null);
    setEditingExpense(null);
    await refreshAll();
  }

  const isPortfolio = tab === 'portfolio';
  const isLoan = tab === 'loan';
  const isEveryday = tab === 'everyday';
  const isAnalytics = tab === 'analytics';
  const isMf = tab === 'mf';
  const isSpending = tab === 'spending';
  const categories = spending
    ? [...new Set([...(spending.knownCategories ?? []), ...(spending.defaultCategories ?? [])])]
    : [];

  if (auth === null) {
    return <p className="py-20 text-center text-sm text-[var(--color-muted)]">Starting…</p>;
  }

  if (!unlocked) {
    return (
      <LockScreen
        mode="unlock"
        onUnlock={handleUnlock}
        lockoutMs={lockoutMs}
      />
    );
  }

  if (!auth.configured && showPinSetup) {
    return <LockScreen mode="setup" onSetup={handleSetupPin} />;
  }

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6">
      <header className="mb-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Personal Finance App</h1>
          <p className="text-xs text-[var(--color-muted)]">
            {isEveryday
              ? 'Day-to-day money in and out, with a running net'
              : isPortfolio
                ? 'LenDen P2P ledger — deposits, payouts, reinvestments, withdrawals'
                : isLoan
                  ? 'Loan against your mutual funds — drawn, repaid, interest, and what it still owes'
                  : 'Where your money goes each month — expenses plus what you moved into LenDen'}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isPortfolio ? (
            <DataTools
              noun="transaction"
              onExport={api.exportCsv}
              onImport={api.importCsv}
              onImported={handleImported}
              onError={setError}
            />
          ) : isLoan ? (
            <DataTools
              noun="loan entry"
              onExport={api.exportLoanCsv}
              onImport={api.importLoanCsv}
              onImported={handleImported}
              onError={setError}
            />
          ) : (
            <DataTools
              noun="expense"
              onExport={api.exportExpensesCsv}
              onImport={api.importExpensesCsv}
              onImported={handleImported}
              onError={setError}
            />
          )}
          {auth.configured ? (
            <button type="button" className="btn" onClick={lockNow} title="Lock the app now">
              🔒 Lock
            </button>
          ) : (
            <button type="button" className="btn" onClick={() => setShowPinSetup(true)}>
              Set a PIN
            </button>
          )}
          <div className="flex overflow-hidden rounded-lg border border-[var(--color-hair)]">
            {['light', 'system', 'dark'].map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTheme(t)}
                className="px-2.5 py-[0.45rem] text-xs font-medium capitalize"
                style={{
                  backgroundColor: theme === t ? 'var(--color-raised)' : 'transparent',
                  color: theme === t ? 'var(--color-ink)' : 'var(--color-muted)',
                }}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </header>

      <nav className="mb-5 flex gap-1 border-b border-[var(--color-line)]" aria-label="Sections">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            aria-current={tab === t.key ? 'page' : undefined}
            className="-mb-px px-4 py-2 text-sm font-semibold"
            style={{
              color: tab === t.key ? 'var(--color-ink)' : 'var(--color-muted)',
              borderBottom: `2px solid ${tab === t.key ? 'var(--color-s1)' : 'transparent'}`,
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {error ? (
        <p
          className="mb-4 flex items-start gap-2 rounded-lg p-3 text-sm"
          style={{
            backgroundColor: 'color-mix(in srgb, var(--color-critical) 10%, transparent)',
            color: 'var(--color-critical)',
          }}
        >
          <span aria-hidden="true">⚠</span>
          <span>{error}</span>
        </p>
      ) : null}

      {status ? (
        <p
          className="mb-4 rounded-lg p-3 text-sm"
          style={{
            backgroundColor: 'color-mix(in srgb, var(--color-good) 12%, transparent)',
            color: 'var(--color-good-text)',
          }}
        >
          {status}
        </p>
      ) : null}

      {loading ? (
        <p className="py-20 text-center text-sm text-[var(--color-muted)]">Loading…</p>
      ) : isPortfolio ? (
        <main className="space-y-4">
          {summary ? (
            <Dashboard
              summary={summary}
              themeKey={theme}
              periods={periods}
              grain={grain}
              onGrainChange={setGrain}
              onSaveNpa={handleSaveNpa}
              busy={busy}
              projection={projection}
              onProjectionChange={setProjOpts}
            />
          ) : null}

          <div ref={formRef}>
            <TransactionForm
              editing={editing}
              onSubmit={handleSubmit}
              onCancelEdit={() => setEditing(null)}
              busy={busy}
              idleCash={summary?.allocation.idle}
            />
          </div>

          <TransactionTable
            rows={transactions}
            sort={sort}
            dir={dir}
            filter={filter}
            editingId={editing?.id}
            onSort={toggleSort}
            onFilter={setFilter}
            onEdit={(row) => {
              setEditing(row);
              formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }}
            onDelete={handleDelete}
          />
        </main>
      ) : isLoan ? (
        <main className="space-y-4">
          {loan ? (
            <LoanView
              summary={loan}
              onSaveSettings={handleSaveLoanSettings}
              onAddOffer={handleAddOffer}
              onDeleteOffer={handleDeleteOffer}
              busy={busy}
              themeKey={theme}
            />
          ) : null}

          <div ref={loanFormRef}>
            <LoanForm
              editing={editingLoan}
              onSubmit={handleLoanSubmit}
              onCancelEdit={() => setEditingLoan(null)}
              busy={busy}
              outstanding={loan?.outstanding}
            />
          </div>

          <LoanTable
            rows={loanEntries}
            sort={lnSort}
            dir={lnDir}
            filter={lnFilter}
            editingId={editingLoan?.id}
            onSort={toggleLoanSort}
            onFilter={setLnFilter}
            onEdit={(row) => {
              setEditingLoan(row);
              loanFormRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }}
            onDelete={handleLoanDelete}
          />
        </main>
      ) : isMf ? (
        <main className="space-y-4">
          {mf ? <MutualFundView summary={mf} onSaveNav={handleSaveNav} busy={busy} /> : null}

          <div ref={mfFormRef}>
            <MutualFundForm
              editing={editingMf}
              onSubmit={handleMfSubmit}
              onCancelEdit={() => setEditingMf(null)}
              busy={busy}
              knownFunds={mf?.knownFunds ?? []}
            />
          </div>

          <MfLog
            rows={mfRows}
            editingId={editingMf?.id}
            onEdit={(row) => {
              setEditingMf(row);
              mfFormRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }}
            onDelete={handleMfDelete}
          />
        </main>
      ) : isAnalytics ? (
        <main className="space-y-4">
          <AnalyticsView
            data={analytics}
            onClear={handleClearActivity}
            busy={busy}
            themeKey={theme}
          />
        </main>
      ) : isEveryday ? (
        <main className="space-y-4">
          {everyday ? (
            <EverydayView
              summary={everyday}
              onEdit={(row) => {
                setEditingEveryday(row);
                everydayFormRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
              }}
              onDelete={handleEverydayDelete}
            />
          ) : null}

          <div ref={everydayFormRef}>
            <EverydayForm
              editing={editingEveryday}
              onSubmit={handleEverydaySubmit}
              onCancelEdit={() => setEditingEveryday(null)}
              busy={busy}
              incomeCategories={everyday?.incomeCategories?.length ? everyday.incomeCategories : (everyday?.defaultIncomeCategories ?? [])}
              expenseCategories={categories}
            />
          </div>

          <EverydayTable
            rows={everyday?.entries ?? []}
            editingId={editingEveryday?.id}
            onEdit={(row) => {
              setEditingEveryday(row);
              everydayFormRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }}
            onDelete={handleEverydayDelete}
          />
        </main>
      ) : (
        <main className="space-y-4">
          {spending ? (
            <SpendingView summary={spending} onMonthChange={setMonth} themeKey={theme} />
          ) : null}

          <div ref={expenseFormRef}>
            <ExpenseForm
              editing={editingExpense}
              onSubmit={handleExpenseSubmit}
              onCancelEdit={() => setEditingExpense(null)}
              busy={busy}
              categories={categories}
            />
          </div>

          <ExpenseTable
            rows={expenses}
            sort={exSort}
            dir={exDir}
            editingId={editingExpense?.id}
            monthLabel={monthLabel(month)}
            onSort={toggleExpenseSort}
            onEdit={(row) => {
              setEditingExpense(row);
              expenseFormRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }}
            onDelete={handleExpenseDelete}
          />
        </main>
      )}
    </div>
  );
}

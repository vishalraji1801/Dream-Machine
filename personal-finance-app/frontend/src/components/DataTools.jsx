import { useRef, useState } from 'react';

export default function DataTools({ onExport, onImport, onImported, onError, noun }) {
  const fileRef = useRef(null);
  const [mode, setMode] = useState('append');
  const [busy, setBusy] = useState(false);

  async function handleExport() {
    try {
      await onExport();
    } catch (err) {
      onError(err.message);
    }
  }

  async function handleFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    const verb = mode === 'replace' ? `REPLACE every existing ${noun} with` : 'add';
    if (!window.confirm(`Import "${file.name}"? This will ${verb} the rows in this file.`)) {
      e.target.value = '';
      return;
    }

    setBusy(true);
    try {
      const csv = await file.text();
      const result = await onImport(csv, mode);
      await onImported(result);
    } catch (err) {
      const detail = err.errors?.length ? err.errors.join(' ') : '';
      onError(`${err.message}${detail && detail !== err.message ? ` — ${detail}` : ''}`);
    } finally {
      setBusy(false);
      e.target.value = '';
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className="btn" onClick={handleExport} disabled={busy}>
        Export CSV
      </button>

      <div className="flex items-center overflow-hidden rounded-lg border border-[var(--color-hair)]">
        <button
          type="button"
          className="btn rounded-none border-0"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
        >
          {busy ? 'Importing…' : 'Import CSV'}
        </button>
        <label className="sr-only" htmlFor="import-mode">Import mode</label>
        <select
          id="import-mode"
          className="border-0 bg-[var(--color-raised)] px-2 py-[0.45rem] text-xs font-medium text-[var(--color-ink)] focus:outline-none"
          value={mode}
          onChange={(e) => setMode(e.target.value)}
        >
          <option value="append">append</option>
          <option value="replace">replace all</option>
        </select>
      </div>

      <input
        ref={fileRef}
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        onChange={handleFile}
      />
    </div>
  );
}

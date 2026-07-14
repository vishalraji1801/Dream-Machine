import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type ConfigField, type ConfigGroup } from "../api";

type Val = number | boolean | string;

export default function Settings() {
  const [groups, setGroups] = useState<ConfigGroup[]>([]);
  const [edits, setEdits] = useState<Record<string, Val>>({}); // "section.key" -> value
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getConfig()
      .then((r) => setGroups(r.groups))
      .catch((e) => setMsg({ kind: "err", text: e instanceof ApiError ? e.message : String(e) }))
      .finally(() => setLoading(false));
  }, []);

  const dirty = useMemo(() => Object.keys(edits).length > 0, [edits]);

  const current = (section: string, f: ConfigField): Val => {
    const id = `${section}.${f.key}`;
    if (id in edits) return edits[id];
    return (f.value ?? (f.type === "bool" ? false : "")) as Val;
  };

  const set = (section: string, key: string, v: Val) =>
    setEdits((e) => ({ ...e, [`${section}.${key}`]: v }));

  const save = async () => {
    setBusy(true);
    setMsg(null);
    const updates: Record<string, Record<string, unknown>> = {};
    for (const id of Object.keys(edits)) {
      const dot = id.indexOf(".");
      const section = id.slice(0, dot);
      const key = id.slice(dot + 1);
      (updates[section] ||= {})[key] = edits[id];
    }
    try {
      const r = await api.putConfig(updates);
      setGroups(r.groups);
      setEdits({});
      setMsg({ kind: "ok", text: `Saved — ${r.applies}.` });
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <div className="text-muted">Loading config…</div>;

  return (
    <div className="space-y-4 pb-24">
      <div className="text-sm text-muted">
        Changes are validated against safe bounds and take effect on the next bot start.
      </div>

      {groups.map((g) => (
        <div key={g.section} className="card">
          <div className="label mb-3">{g.label}</div>
          <div className="grid sm:grid-cols-2 gap-x-6 gap-y-3">
            {g.fields.map((f) => (
              <FieldRow
                key={f.key}
                field={f}
                value={current(g.section, f)}
                onChange={(v) => set(g.section, f.key, v)}
              />
            ))}
          </div>
        </div>
      ))}

      {/* sticky save bar */}
      <div className="fixed bottom-0 inset-x-0 bg-bg/95 backdrop-blur border-t border-line">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-3">
          {msg && (
            <span className={`text-sm ${msg.kind === "ok" ? "text-up" : "text-down"}`}>{msg.text}</span>
          )}
          <div className="ml-auto flex gap-2">
            <button className="btn" disabled={!dirty || busy} onClick={() => setEdits({})}>
              Discard
            </button>
            <button className="btn btn-accent" disabled={!dirty || busy} onClick={save}>
              {busy ? "Saving…" : dirty ? `Save ${Object.keys(edits).length} change(s)` : "Saved"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function FieldRow({
  field: f,
  value,
  onChange,
}: {
  field: ConfigField;
  value: Val;
  onChange: (v: Val) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3">
      <span className="text-sm">
        {f.label}
        {f.unit && <span className="text-muted"> ({f.unit})</span>}
        {f.help && <span className="block text-xs text-muted">{f.help}</span>}
      </span>
      <span className="shrink-0">
        {f.type === "bool" ? (
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
            className="w-5 h-5 accent-accent"
          />
        ) : f.type === "select" ? (
          <select
            value={String(value)}
            onChange={(e) => onChange(e.target.value)}
            className="bg-panel2 border border-line rounded-lg px-2 py-1.5 text-sm outline-none focus:border-accent"
          >
            {f.options.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        ) : f.type === "time" ? (
          <input
            type="time"
            value={String(value)}
            onChange={(e) => onChange(e.target.value)}
            className="bg-panel2 border border-line rounded-lg px-2 py-1.5 text-sm outline-none focus:border-accent"
          />
        ) : f.type === "number" ? (
          <input
            type="number"
            value={value === "" ? "" : Number(value)}
            min={f.min ?? undefined}
            max={f.max ?? undefined}
            step={f.step ?? undefined}
            onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
            className="w-28 bg-panel2 border border-line rounded-lg px-2 py-1.5 text-sm text-right font-mono outline-none focus:border-accent"
          />
        ) : (
          <input
            type="text"
            value={String(value)}
            onChange={(e) => onChange(e.target.value)}
            placeholder="(none)"
            className="w-36 bg-panel2 border border-line rounded-lg px-2 py-1.5 text-sm outline-none focus:border-accent"
          />
        )}
      </span>
    </label>
  );
}

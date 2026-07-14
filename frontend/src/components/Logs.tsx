import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";

export default function Logs() {
  const [files, setFiles] = useState<{ name: string; size: number }[]>([]);
  const [active, setActive] = useState("");
  const [lines, setLines] = useState<string[]>([]);
  const [auto, setAuto] = useState(true);
  const boxRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    api.logsList().then((r) => {
      setFiles(r.files);
      if (r.files.length) setActive((a) => a || r.files[0].name);
    }).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    if (!active) return;
    try {
      const r = await api.logTail(active, 400);
      setLines(r.lines);
    } catch {
      /* ignore */
    }
  }, [active]);

  useEffect(() => {
    load();
    if (!auto) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [load, auto]);

  useEffect(() => {
    if (auto && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [lines, auto]);

  const colored = (l: string) => {
    if (/ERROR|CRITICAL/.test(l)) return "text-down";
    if (/WARN/.test(l)) return "text-warn";
    if (/INFO/.test(l)) return "text-muted";
    return "";
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select className="ctl" value={active} onChange={(e) => setActive(e.target.value)}>
          {files.map((f) => (
            <option key={f.name} value={f.name}>
              {f.name} ({Math.round(f.size / 1024)} KB)
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-sm text-muted">
          <input type="checkbox" className="accent-accent" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          auto-refresh
        </label>
        <button className="btn ml-auto" onClick={load}>Refresh</button>
      </div>

      <pre
        ref={boxRef}
        className="card font-mono text-xs leading-5 overflow-auto h-[70vh] whitespace-pre-wrap"
      >
        {lines.length === 0 ? (
          <span className="text-muted">No output.</span>
        ) : (
          lines.map((l, i) => (
            <div key={i} className={colored(l)}>
              {l}
            </div>
          ))
        )}
      </pre>
    </div>
  );
}

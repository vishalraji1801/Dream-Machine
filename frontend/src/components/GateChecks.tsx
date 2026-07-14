import type { Status } from "../api";

export default function GateChecks({ status }: { status: Status | null }) {
  const checks = status?.gate_checks;
  if (!checks || Object.keys(checks).length === 0) return null;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="label">Go-live gate</div>
        <span className={`text-xs ${status?.gate_ready ? "text-up" : "text-muted"}`}>
          {status?.gate_ready ? "READY" : "not yet"}
        </span>
      </div>
      <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
        {Object.entries(checks).map(([name, passed]) => (
          <div key={name} className="flex items-center gap-2">
            <span className={passed ? "text-up" : "text-down"}>{passed ? "✓" : "✗"}</span>
            <span className="text-muted">{name.replace(/_/g, " ")}</span>
          </div>
        ))}
      </div>
      <div className="text-xs text-muted mt-3">
        Passing the gate is required, but going live still needs an explicit confirm.
      </div>
    </div>
  );
}

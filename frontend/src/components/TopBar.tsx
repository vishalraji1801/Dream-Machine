import { clearToken, type Status } from "../api";

export default function TopBar({
  status,
  running,
  mode,
  connected,
}: {
  status: Status | null;
  running: boolean;
  mode: "paper" | "live";
  connected: boolean;
}) {
  return (
    <header className="sticky top-0 z-10 bg-bg/90 backdrop-blur border-b border-line">
      <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-3">
        <div className="font-semibold">Dream Machine</div>

        <span
          className={`text-xs px-2 py-0.5 rounded-full border ${
            mode === "live" ? "border-down text-down" : "border-accent text-accent"
          }`}
        >
          {mode.toUpperCase()}
        </span>

        <span className="flex items-center gap-1.5 text-xs text-muted">
          <span className={`w-2 h-2 rounded-full ${running ? "bg-up" : "bg-muted"}`} />
          {running ? "running" : "stopped"}
        </span>

        <span className="hidden sm:block text-xs text-muted truncate">
          {status?.market || ""}
        </span>

        <div className="ml-auto flex items-center gap-3">
          <span
            title={connected ? "Live feed connected" : "Reconnecting…"}
            className={`w-2 h-2 rounded-full ${connected ? "bg-up" : "bg-warn animate-pulse"}`}
          />
          <button
            className="text-xs text-muted hover:text-white"
            onClick={() => {
              clearToken();
              location.reload();
            }}
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}

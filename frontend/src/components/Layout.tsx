import { NavLink, Outlet } from "react-router-dom";
import { clearToken } from "../api";
import { useLiveCtx } from "../LiveContext";

const tabs = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/settings", label: "Settings", end: false },
];

export default function Layout() {
  const { status, running, mode, connected } = useLiveCtx();

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-10 bg-bg/90 backdrop-blur border-b border-line">
        <div className="max-w-5xl mx-auto px-4 pt-3 pb-2 flex items-center gap-3">
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
          <span className="hidden sm:block text-xs text-muted truncate">{status?.market || ""}</span>
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
        <nav className="max-w-5xl mx-auto px-4 pb-2 flex gap-2">
          {tabs.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              end={t.end}
              className={({ isActive }) =>
                `px-3 py-1 rounded-lg text-sm ${
                  isActive ? "bg-panel2 text-white" : "text-muted hover:text-white"
                }`
              }
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="max-w-5xl mx-auto p-4">
        <Outlet />
      </main>
    </div>
  );
}

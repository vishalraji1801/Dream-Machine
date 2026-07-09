// Shared live state: one WebSocket + one status/control poll for the whole app,
// so every page (and the header) reads the same source without duplicate feeds.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type ControlState, type Status } from "./api";
import { useLive, type LiveSnapshot } from "./useLive";

interface LiveCtx {
  snap: LiveSnapshot | null;
  connected: boolean;
  status: Status | null;
  ctl: ControlState | null;
  running: boolean;
  mode: "paper" | "live";
  refresh: () => void;
}

const Ctx = createContext<LiveCtx | null>(null);

export function LiveProvider({ children }: { children: ReactNode }) {
  const { snap, connected } = useLive();
  const [status, setStatus] = useState<Status | null>(null);
  const [ctl, setCtl] = useState<ControlState | null>(null);

  const refresh = useCallback(async () => {
    const [st, cs] = await Promise.allSettled([api.status(), api.controlState()]);
    if (st.status === "fulfilled") setStatus(st.value);
    if (cs.status === "fulfilled") setCtl(cs.value);
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  const running = snap?.running ?? ctl?.running ?? false;
  const mode = snap?.mode ?? ctl?.mode ?? "paper";

  return (
    <Ctx.Provider value={{ snap, connected, status, ctl, running, mode, refresh }}>
      {children}
    </Ctx.Provider>
  );
}

export function useLiveCtx(): LiveCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLiveCtx must be used within LiveProvider");
  return v;
}

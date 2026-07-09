// Live snapshot over WebSocket, with auto-reconnect. Falls back silently to the
// last snapshot while disconnected; the dashboard also polls REST as a backstop.
import { useEffect, useRef, useState } from "react";
import { getToken, type Position } from "./api";

export interface LiveSnapshot {
  type: "snapshot";
  running: boolean;
  mode: "paper" | "live";
  positions: Position[];
  daily_pnl: number;
  trades_today: number;
  stale: boolean;
}

export function useLive() {
  const [snap, setSnap] = useState<LiveSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws/live?token=${encodeURIComponent(getToken())}`);
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onmessage = (e) => {
        try {
          setSnap(JSON.parse(e.data));
        } catch {
          /* ignore malformed frame */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      wsRef.current?.close();
    };
  }, []);

  return { snap, connected };
}

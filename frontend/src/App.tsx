import { useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { getToken, verifyToken } from "./api";
import { LiveProvider } from "./LiveContext";
import Login from "./components/Login";
import Layout from "./components/Layout";
import Dashboard from "./components/Dashboard";
import Settings from "./components/Settings";
import Backtest from "./components/Backtest";
import Strategies from "./components/Strategies";

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    if (!getToken()) {
      setAuthed(false);
      return;
    }
    verifyToken().then(setAuthed);
  }, []);

  if (authed === null) {
    return <div className="min-h-full grid place-items-center text-muted">Connecting…</div>;
  }
  if (!authed) return <Login onAuthed={() => setAuthed(true)} />;

  return (
    <BrowserRouter>
      <LiveProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="backtest" element={<Backtest />} />
            <Route path="strategies" element={<Strategies />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<Dashboard />} />
          </Route>
        </Routes>
      </LiveProvider>
    </BrowserRouter>
  );
}

import { useEffect, useState } from "react";
import { getToken, verifyToken } from "./api";
import Login from "./components/Login";
import Dashboard from "./components/Dashboard";

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
  return authed ? <Dashboard /> : <Login onAuthed={() => setAuthed(true)} />;
}

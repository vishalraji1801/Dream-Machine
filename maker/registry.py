"""maker/registry.py — append-only trial registry (Strategy Maker, spec section 4).

RULE 1: every evaluation is a logged trial; the registry is append-only. Deleting or
not-recording a trial is the one unforgivable bug. Append-only is enforced at the DB
level with BEFORE UPDATE/DELETE triggers, not just by convention.

The statistical unit is the FAMILY = hash(block structure + direction), IGNORING
timeframe and parameter values. A candidate tried on many TFs / param combos is ONE
family, many trial rows. N_effective = distinct families evaluated at SCREEN or beyond
(GEN_REJECTs do not count toward the search-effort bar).
"""
import hashlib
import json
import sqlite3
from datetime import datetime

from maker.grammar import Candidate

# stages a candidate passes through; only these count toward N_effective
STAGES = ("GEN_REJECT", "SCREEN", "GAUNTLET", "RESERVE", "PAPER")
EVALUATED_STAGES = ("SCREEN", "GAUNTLET", "RESERVE", "PAPER")


def family_id(candidate: Candidate) -> str:
    """hash(block structure + direction), IGNORING timeframe and params."""
    structure = sorted((slot, bi.name) for slot, bi in candidate.blocks.items())
    raw = json.dumps({"dir": candidate.direction, "blocks": structure}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class Registry:
    def __init__(self, path: str = "data_cache/maker_trials.db"):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        c = self._conn
        c.execute("""CREATE TABLE IF NOT EXISTS trials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cid TEXT, family TEXT, sleeve TEXT DEFAULT 'swing',
            stage TEXT, status TEXT, pf_required REAL,
            metrics_json TEXT, config_version TEXT, data_span TEXT,
            notes TEXT, created_at TEXT)""")
        # RULE 1 — append-only, enforced by the database itself.
        c.execute("""CREATE TRIGGER IF NOT EXISTS trials_no_update BEFORE UPDATE ON trials
                     BEGIN SELECT RAISE(FAIL, 'trials is append-only (RULE 1)'); END""")
        c.execute("""CREATE TRIGGER IF NOT EXISTS trials_no_delete BEFORE DELETE ON trials
                     BEGIN SELECT RAISE(FAIL, 'trials is append-only (RULE 1)'); END""")
        c.commit()

    def record(self, cid: str, family: str, stage: str, status: str,
               sleeve: str = "swing", pf_required: float = None, metrics: dict = None,
               config_version: str = "", data_span: str = "", notes: str = "",
               created_at: str = None) -> int:
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}")
        self._conn.execute(
            "INSERT INTO trials (cid, family, sleeve, stage, status, pf_required, "
            "metrics_json, config_version, data_span, notes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cid, family, sleeve, stage, status, pf_required,
             json.dumps(metrics or {}), config_version, data_span, notes,
             created_at or datetime.now().isoformat(timespec="seconds")))
        self._conn.commit()
        return self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def n_effective(self, sleeve: str = None) -> int:
        """Distinct families evaluated at SCREEN or beyond (the honest search-effort N)."""
        q = ("SELECT COUNT(DISTINCT family) FROM trials WHERE stage IN "
             f"({','.join('?' * len(EVALUATED_STAGES))})")
        args = list(EVALUATED_STAGES)
        if sleeve:
            q += " AND sleeve = ?"
            args.append(sleeve)
        return self._conn.execute(q, args).fetchone()[0]

    def count(self, stage: str = None, status: str = None) -> int:
        q, args = "SELECT COUNT(*) FROM trials WHERE 1=1", []
        if stage:
            q += " AND stage = ?"; args.append(stage)
        if status:
            q += " AND status = ?"; args.append(status)
        return self._conn.execute(q, args).fetchone()[0]

    def rows(self) -> list:
        return [dict(r) for r in self._conn.execute("SELECT * FROM trials ORDER BY id")]

    def close(self):
        self._conn.close()

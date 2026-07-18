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


# ── prior-campaign seeds (section 11.4) — the bar must remember past search ────
# Swing: the 19-strategy campaign, each strategy = one family, status per the broad
# 202-name retest. Intraday: 14 strategies x 4 timeframes = 56 FAILED families, so
# N_effective(intraday) starts at 56 and the intraday bar starts ~pf_required(56)~1.31.
_SWING_PRIOR = {
    "donchian_trend_tsl": True, "volatility_contraction_breakout": True,
    "double_reversal": True, "bb_mean_reversion": True, "index_dip_reversion": True,
    "abcd_pattern": True, "dip_buy_momentum": True, "head_shoulders": True,
    "ma_pullback": False, "fair_value_gap": False, "trendline_bounce": False,
    "inside_bar_breakout": False, "rsi_reversion": False, "engulfing_macd": False,
    "supertrend": False, "orb_nifty": False, "red_to_green_vwap": False,
    "vwap_break_short": False, "vwap_squeeze": False,
}
_INTRADAY_PRIOR_STRATS = [
    "supertrend", "orb_nifty", "volatility_contraction_breakout", "rsi_reversion",
    "engulfing_macd", "inside_bar_breakout", "red_to_green_vwap", "vwap_break_short",
    "vwap_squeeze", "ma_pullback", "fair_value_gap", "trendline_bounce",
    "abcd_pattern", "head_shoulders"]
_INTRADAY_PRIOR_TFS = ["5m", "15m", "30m", "60m"]


def _seed_family(prefix: str, key: str) -> str:
    return prefix + hashlib.sha256(key.encode()).hexdigest()[:10]


def seed_registry(reg: Registry) -> dict:
    """Seed both sleeves with the pre-maker campaign so the bar remembers past search."""
    for name, passed in _SWING_PRIOR.items():
        reg.record(cid="seed:" + name, family=_seed_family("sw_", name), stage="SCREEN",
                   status="PASS" if passed else "FAIL", sleeve="swing",
                   notes="pre-maker swing campaign (broad 202-name retest)")
    for strat in _INTRADAY_PRIOR_STRATS:
        for tf in _INTRADAY_PRIOR_TFS:
            reg.record(cid=f"seed:{strat}:{tf}", family=_seed_family("id_", strat + tf),
                       stage="SCREEN", status="FAIL", sleeve="intraday",
                       notes="pre-maker intraday campaign (14x4TF, all failed OOS)")
    return {"swing": reg.n_effective("swing"), "intraday": reg.n_effective("intraday")}

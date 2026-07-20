"""Strategy Maker — Commit 6: reserve lock + single-shot (tests 7-8)."""
import pandas as pd
import pytest

from maker.grammar import make_candidate
from maker.registry import Registry, family_id
from maker import reserve as R


def _lock(tmp_path, cutoff="2023-01-01"):
    return R.write_lock(cutoff, ["AAA", "BBB"], path=str(tmp_path / "reserve_lock.json"))


def _df(n=1600):
    return pd.DataFrame({"timestamp": pd.date_range("2018-01-01", periods=n, freq="D"),
                         "open": range(n), "high": range(n), "low": range(n),
                         "close": range(n), "volume": [1] * n})


def _cand(mult=5):
    return make_candidate("long", {
        "setup": ("nday_extreme", {"lookback": 100, "side": "high"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("atr_trail", {"mult": mult, "period": 14})})


# ── test 7: reserve lock ──────────────────────────────────────────────────────

def test_lock_is_written_once(tmp_path):
    _lock(tmp_path)
    with pytest.raises(FileExistsError):
        _lock(tmp_path)


def test_screen_never_sees_past_the_cutoff(tmp_path):
    lock = _lock(tmp_path)
    screen = R.screen_candles(_df(), lock)
    assert pd.to_datetime(screen["timestamp"]).max() < pd.to_datetime("2023-01-01")


def test_reserve_read_forbidden_outside_evaluate(tmp_path):
    lock = _lock(tmp_path)
    with pytest.raises(PermissionError):
        R.reserve_candles(_df(), lock)


# ── test 8: single-shot per family ────────────────────────────────────────────

def _fake_pass(cand, reserve_by_symbol, cfg):
    return {"trades": 40, "pf": 1.6, "net": 5000, "top3_frac": 0.2, "rank": 5.0}


def _fake_fail(cand, reserve_by_symbol, cfg):
    return {"trades": 40, "pf": 1.05, "net": 500, "top3_frac": 0.2, "rank": 3.0}


def _fake_outlier(cand, reserve_by_symbol, cfg):
    # strong pf/trades/net, but the top 3 trades are >60% of net -> outlier-carried
    return {"trades": 40, "pf": 2.5, "net": 5000, "top3_frac": 0.72, "rank": 5.0}


def test_reserve_rejects_outlier_carried_even_if_pf_clears(tmp_path):
    lock = _lock(tmp_path)
    reg = Registry(str(tmp_path / "trials.db"))
    c = _cand()
    status, _ = R.evaluate_once(c, family_id(c), {"AAA": _df()}, lock, reg,
                                n_effective=100, cfg={}, evaluator=_fake_outlier)
    assert status == "DEAD"          # concentration guard: as strict as the screen


def test_reserve_pass_marks_family_alive(tmp_path):
    lock = _lock(tmp_path)
    reg = Registry(str(tmp_path / "trials.db"))
    c = _cand()
    status, m = R.evaluate_once(c, family_id(c), {"AAA": _df()}, lock, reg,
                                n_effective=100, cfg={}, evaluator=_fake_pass)
    assert status == "ALIVE"
    assert reg.rows()[0]["stage"] == "RESERVE" and reg.rows()[0]["status"] == "ALIVE"


def test_reserve_single_shot_per_family(tmp_path):
    lock = _lock(tmp_path)
    reg = Registry(str(tmp_path / "trials.db"))
    c1 = _cand(mult=5)
    R.evaluate_once(c1, family_id(c1), {"AAA": _df()}, lock, reg, 100, {}, evaluator=_fake_fail)
    # a modified candidate: NEW cid, but SAME family -> still no second shot
    c2 = _cand(mult=6)
    assert c2.cid != c1.cid and family_id(c2) == family_id(c1)
    with pytest.raises(RuntimeError):
        R.evaluate_once(c2, family_id(c2), {"AAA": _df()}, lock, reg, 100, {}, evaluator=_fake_pass)


def test_void_supersedes_and_reopens_the_single_shot(tmp_path):
    """Append-only correction: a VOID marker invalidates a prior (buggy) verdict, reopens
    the single shot, and the re-run's result becomes the effective verdict — nothing deleted."""
    lock = _lock(tmp_path)
    reg = Registry(str(tmp_path / "trials.db"))
    c = _cand()
    fam = family_id(c)
    # 1. a first (say buggy) DEAD verdict is recorded
    R.evaluate_once(c, fam, {"AAA": _df()}, lock, reg, 100, {}, evaluator=_fake_fail)
    assert R.reserve_verdict(reg.rows(), fam)["status"] == "DEAD"
    # 2. invalidate it -> family may take a fresh shot again
    R.invalidate_reserve(reg, fam, reason="bug: 0-trade warmup")
    assert R.reserve_verdict(reg.rows(), fam) is None
    # 3. re-run -> new verdict stands as the effective one
    status, _ = R.evaluate_once(c, fam, {"AAA": _df()}, lock, reg, 100, {}, evaluator=_fake_pass)
    assert status == "ALIVE"
    assert R.reserve_verdict(reg.rows(), fam)["status"] == "ALIVE"
    assert R.effective_reserve_table(reg.rows())[fam] == "ALIVE"
    # 4. and it is single-shot again (no fresh VOID) -> blocked
    with pytest.raises(RuntimeError):
        R.evaluate_once(c, fam, {"AAA": _df()}, lock, reg, 100, {}, evaluator=_fake_fail)
    # audit trail preserved: DEAD, VOID, ALIVE all still present (append-only)
    stages = [(r["stage"], r["status"]) for r in reg.rows() if r["family"] == fam
              and r["stage"] == "RESERVE"]
    assert stages == [("RESERVE", "DEAD"), ("RESERVE", "VOID"), ("RESERVE", "ALIVE")]


def test_reserve_fail_uses_the_rising_bar(tmp_path):
    lock = _lock(tmp_path)
    reg = Registry(str(tmp_path / "trials.db"))
    c = _cand()
    # pf 1.25 fails the N=1000 bar (1.50) but the stamped bar proves which was applied
    metrics = {"trades": 40, "pf": 1.25, "net": 500, "top3_frac": 0.2, "rank": 3.0}
    status, _ = R.evaluate_once(c, family_id(c), {"AAA": _df()}, lock, reg,
                                n_effective=1000, cfg={}, evaluator=lambda *a: metrics)
    assert status == "DEAD"
    assert reg.rows()[0]["pf_required"] == 1.50


# ── warmup regression: a short holdout must NOT auto-DEAD every candidate ──────

def test_reserve_eval_frame_prepends_warmup_and_is_gated(tmp_path):
    lock = _lock(tmp_path, cutoff="2021-01-01")
    df = pd.DataFrame({"timestamp": pd.date_range("2018-01-01", periods=1500, freq="D"),
                       "open": range(1500), "high": range(1500), "low": range(1500),
                       "close": range(1500), "volume": [1] * 1500})
    R._UNLOCKED = True
    try:
        f = R._reserve_eval_frame(df, lock, warmup=260)
    finally:
        R._UNLOCKED = False
    cutoff = pd.to_datetime("2021-01-01")
    ts = pd.to_datetime(f["timestamp"])
    assert (ts < cutoff).sum() == 260          # exactly the warmup tail is prepended
    assert (ts >= cutoff).sum() > 0            # plus the real post-cutoff test window
    with pytest.raises(PermissionError):       # still RULE-2 gated when locked
        R._reserve_eval_frame(df, lock)


def test_reserve_trades_despite_holdout_shorter_than_warmup(tmp_path):
    """The bug: post-cutoff slice (< WINDOW bars) can't warm the rolling window, so every
    candidate produced 0 trades -> false DEAD. With warmup, the strategy trades OOS."""
    import math
    import os

    import yaml

    from maker.screen import WINDOW
    cfg = yaml.safe_load(open(os.path.join("config", "config.yaml")))
    cfg["strategy"]["regime_filter_enabled"] = False
    cfg["trading"]["entry_start_time"] = ""; cfg["trading"]["entry_end_time"] = ""
    cfg["costs"]["product"] = "delivery"

    def series(n=1400, phase=0.0):
        close = [100 + 30 * math.sin(i / 15 + phase) + i * 0.08 for i in range(n)]
        return pd.DataFrame({"timestamp": pd.date_range("2019-01-01", periods=n, freq="D"),
                             "open": close, "high": [c + 1 for c in close],
                             "low": [c - 1 for c in close], "close": close,
                             "volume": [100000] * n})
    df = series()
    # cutoff leaves ~120 post-cutoff bars — FAR under WINDOW, so the old post-only slice
    # would give 0 trades on every candidate.
    cutoff = str(pd.to_datetime(df["timestamp"].iloc[-120]).date())
    assert (pd.to_datetime(df["timestamp"]) >= pd.to_datetime(cutoff)).sum() < WINDOW
    lock = R.write_lock(cutoff, ["AAA", "BBB"], path=str(tmp_path / "reserve_lock.json"))
    reg = Registry(str(tmp_path / "trials.db"))
    c = make_candidate("long", {
        "setup": ("nday_extreme", {"lookback": 50, "side": "high"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("atr_trail", {"mult": 4, "period": 14})})
    status, m = R.evaluate_once(c, family_id(c), {"AAA": df, "BBB": series(1400, phase=1.3)},
                                lock, reg, n_effective=50, cfg=cfg)
    assert m["trades"] > 0, "warmup fix failed — reserve still produces 0 trades"

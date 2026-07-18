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

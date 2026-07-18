"""Strategy Maker — Commit 13: registry seeding with the prior campaign (test 14)."""
from maker.bar import pf_required
from maker.registry import Registry, seed_registry


def test_seed_sets_starting_n_and_bar(tmp_path):
    reg = Registry(str(tmp_path / "t.db"))
    counts = seed_registry(reg)
    assert counts["intraday"] == 56           # 14 strategies x 4 timeframes
    assert counts["swing"] == 19
    # the intraday bar therefore STARTS elevated — the 56 failures are remembered
    assert round(pf_required(56), 2) == 1.31
    assert pf_required(reg.n_effective("intraday")) > pf_required(10)


def test_seed_intraday_all_failed(tmp_path):
    reg = Registry(str(tmp_path / "t.db"))
    seed_registry(reg)
    intraday_rows = [r for r in reg.rows() if r["sleeve"] == "intraday"]
    assert len(intraday_rows) == 56
    assert all(r["status"] == "FAIL" for r in intraday_rows)


def test_seed_swing_records_known_winners(tmp_path):
    reg = Registry(str(tmp_path / "t.db"))
    seed_registry(reg)
    passes = [r for r in reg.rows() if r["sleeve"] == "swing" and r["status"] == "PASS"]
    assert len(passes) == 8               # the 8 that passed the broad retest

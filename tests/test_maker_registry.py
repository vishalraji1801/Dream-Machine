"""Strategy Maker — Commit 4: registry immutability + N_effective + bar (tests 4-5)."""
import sqlite3

import pytest

from maker.bar import pf_required
from maker.grammar import make_candidate
from maker.registry import Registry, family_id


def _cand(lookback=100, mult=5):
    return make_candidate("long", {
        "setup": ("nday_extreme", {"lookback": lookback, "side": "high"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("atr_trail", {"mult": mult, "period": 14}),
    })


def test_bar_exact_values():
    assert pf_required(10) == 1.20
    assert pf_required(100) == 1.35
    assert pf_required(1000) == 1.50
    assert pf_required(5) == 1.20            # floored at N=10


def test_bar_is_monotone_nondecreasing():
    vals = [pf_required(n) for n in (10, 50, 100, 500, 1000)]
    assert vals == sorted(vals)


def test_family_ignores_params(tmp_path):
    # two candidates, same structure, different params -> SAME family
    a, b = _cand(lookback=100, mult=5), _cand(lookback=200, mult=3)
    assert a.cid != b.cid
    assert family_id(a) == family_id(b)


def test_registry_is_append_only(tmp_path):
    reg = Registry(str(tmp_path / "t.db"))
    c = _cand()
    reg.record(c.cid, family_id(c), "SCREEN", "PASS", pf_required=1.2)
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    with pytest.raises(sqlite3.Error):                    # RAISE(FAIL) -> IntegrityError
        conn.execute("UPDATE trials SET status='FAIL'"); conn.commit()
    with pytest.raises(sqlite3.Error):
        conn.execute("DELETE FROM trials"); conn.commit()


def test_n_effective_counts_families_not_rows(tmp_path):
    reg = Registry(str(tmp_path / "t.db"))
    fam = None
    for lb, mult in [(100, 5), (150, 4), (200, 3)]:      # 3 rows, ONE family
        c = _cand(lb, mult); fam = family_id(c)
        reg.record(c.cid, fam, "SCREEN", "FAIL", pf_required=1.2)
    # a GEN_REJECT of a DIFFERENT family must NOT count toward N_effective
    other = make_candidate("long", {
        "setup": ("band_touch", {"bollinger": (20, 2.0), "side": "lower"}),
        "trigger": ("limit_below", {"offset_pct": 3}),
        "exit": ("opposite_band", {"bollinger": (20, 2.0)})})
    reg.record(other.cid, family_id(other), "GEN_REJECT", "FAIL")
    assert reg.count() == 4
    assert reg.n_effective() == 1                          # one evaluated family


def test_pf_required_is_stamped_on_rows(tmp_path):
    reg = Registry(str(tmp_path / "t.db"))
    c = _cand()
    reg.record(c.cid, family_id(c), "GAUNTLET", "PASS", pf_required=1.35)
    assert reg.rows()[0]["pf_required"] == 1.35

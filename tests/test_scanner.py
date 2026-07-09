from src.scanner import rank, score_quote

CFG = {"scanner": {"top_n": 2, "w_pct_change": 1.0, "w_range_pos": 2.0, "w_gap": 0.5}}


def _q(symbol, ltp, prev, high, low, open_=None):
    return {"symbol": symbol, "ltp": ltp, "close": prev, "high": high, "low": low,
            "open": open_ if open_ is not None else prev}


def test_score_none_without_prices():
    assert score_quote({"ltp": None, "close": 100}, CFG) is None
    assert score_quote({"ltp": 100, "close": None}, CFG) is None


def test_score_rewards_bigger_move():
    small = score_quote(_q("A", 101, 100, 102, 99), CFG)["score"]
    big = score_quote(_q("B", 105, 100, 106, 99), CFG)["score"]
    assert big > small


def test_pct_change_computed():
    s = score_quote(_q("A", 110, 100, 111, 99), CFG)
    assert s["pct_change"] == 10.0


def test_rank_returns_top_n_sorted():
    quotes = {
        "A": _q("A", 101, 100, 102, 99),    # +1%
        "B": _q("B", 108, 100, 109, 99),    # +8% (strongest)
        "C": _q("C", 103, 100, 104, 99),    # +3%
    }
    ranked = rank(quotes, CFG)
    assert len(ranked) == 2                 # top_n = 2
    assert ranked[0]["symbol"] == "B"
    assert ranked[0]["rank"] == 1
    assert ranked[1]["symbol"] == "C"


def test_rank_uses_dict_key_as_symbol():
    ranked = rank({"XYZ": {"ltp": 105, "close": 100, "high": 106, "low": 99, "open": 100}}, CFG)
    assert ranked[0]["symbol"] == "XYZ"


def test_rank_skips_unpriced():
    ranked = rank({"A": {"ltp": None, "close": 100}, "B": _q("B", 105, 100, 106, 99)}, CFG)
    assert [r["symbol"] for r in ranked] == ["B"]


# ── A0: full rankings + shadow scan ───────────────────────────────────────────

from src.scanner import shadow_scan


def test_rank_limit_none_returns_all():
    quotes = {c: _q(c, 100 + i, 100, 101 + i, 99) for i, c in enumerate("ABCDE")}
    full = rank(quotes, {"scanner": {"top_n": 2}}, limit=None)
    assert len(full) == 5                      # all, not top_n
    assert [r["rank"] for r in full] == [1, 2, 3, 4, 5]


def test_shadow_scan_splits_ranked_and_rejected():
    quotes = {
        "A": _q("A", 105, 100, 106, 99),
        "B": _q("B", 108, 100, 109, 99),
        "DEAD": {"ltp": None, "close": None},   # unscorable
    }
    ranked, rejected = shadow_scan(quotes, CFG)
    assert {r["symbol"] for r in ranked} == {"A", "B"}
    assert rejected == [{"symbol": "DEAD", "reason": "no_quote_data"}]


# ── A1: RVOL in scoring & shadow ──────────────────────────────────────────────

def test_rvol_boosts_score_and_is_persisted():
    base = _q("A", 105, 100, 106, 99)
    plain = score_quote({**base}, CFG)
    with_rvol = score_quote({**base, "rvol": 3.0}, {**CFG, "universe": {"rvol": {"score_weight": 1.0}}})
    assert with_rvol["score"] > plain["score"]
    assert with_rvol["rvol"] == 3.0


def test_shadow_scan_excludes_when_require_rvol():
    quotes = {"A": {**_q("A", 105, 100, 106, 99), "rvol": 2.0},
              "B": {**_q("B", 108, 100, 109, 99)}}    # no rvol
    cfg = {**CFG, "universe": {"require_rvol": True, "rvol": {"score_weight": 0.4}}}
    ranked, rejected = shadow_scan(quotes, cfg)
    assert [r["symbol"] for r in ranked] == ["A"]
    assert rejected == [{"symbol": "B", "reason": "rvol_unavailable"}]

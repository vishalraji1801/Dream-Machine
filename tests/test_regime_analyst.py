"""Commit 6 — ledger→regime_fit analyst + small-sample guard (test 8)."""
from src.regime import Regime, RegimeState
from src.regime_analyst import compute_regime_fit, trusted_fit, write_regime_fit
from src.router import PremarketAllocation, RouterConfig, route
from src.strategy_meta import fit_for, load_strategy_meta


def _trades(strategy, regime, pnls):
    return [{"strategy": strategy, "regime": regime, "pnl": p} for p in pnls]


def test_bucketing_and_status():
    trades = (_trades("A", "STRONG_TREND_UP", [100, -40] * 20)      # 40 trades
              + _trades("A", "HIGH_VOL_CHOP", [50, -60] * 5))       # 10 trades
    fit = compute_regime_fit(trades, min_trades=30)
    assert fit["A"]["STRONG_TREND_UP"]["status"] == "ok"
    assert fit["A"]["STRONG_TREND_UP"]["trades"] == 40
    assert fit["A"]["HIGH_VOL_CHOP"]["status"] == "insufficient_data"   # 10 < 30


# ── test 8: small-sample bucket treated as neutral, not an edge ────────────────

def test_small_sample_excluded_and_neutral_in_router():
    trades = (_trades("A", "STRONG_TREND_UP", [100, -40] * 20)      # 40 -> ok
              + _trades("A", "HIGH_VOL_CHOP", [200] * 10))          # 10 -> insufficient
    trusted = trusted_fit(compute_regime_fit(trades, 30), 30)
    assert "STRONG_TREND_UP" in trusted["A"]
    assert "HIGH_VOL_CHOP" not in trusted.get("A", {})              # dropped

    # inject the trusted map into a strategy meta; the small-sample regime must
    # produce trade-nothing (fit treated as neutral), the ok regime must route.
    meta = load_strategy_meta({
        "name": "A",
        "regime_param_sets": {
            "STRONG_TREND_UP": {"multiplier": 2.1, "validated": True},
            "HIGH_VOL_CHOP": {"multiplier": 3.0, "validated": True},
        },
        "regime_fit": {r: v for r, v in trusted["A"].items()},
    })
    assert fit_for(meta, Regime.HIGH_VOL_CHOP, 30) is None          # neutral
    prem, cfg = PremarketAllocation(1.0), RouterConfig(mode="live")
    assert route(RegimeState(Regime.HIGH_VOL_CHOP, 1.0, 5, {}, "v"), [meta], prem, cfg) == []
    assert len(route(RegimeState(Regime.STRONG_TREND_UP, 1.0, 5, {}, "v"), [meta], prem, cfg)) == 1


def test_infinite_pf_bucket_not_trusted():
    # a bucket with no losers has undefined PF -> not trustworthy for weighting
    fit = compute_regime_fit(_trades("A", "QUIET", [10] * 40), 30)
    assert fit["A"]["QUIET"]["pf"] is None
    assert trusted_fit(fit, 30) == {}


def test_write_regime_fit_updates_yaml(tmp_path):
    import yaml
    p = tmp_path / "A.yaml"
    p.write_text("name: A\nregime_param_sets:\n  default: {validated: true}\n", encoding="utf-8")
    fit = compute_regime_fit(_trades("A", "STRONG_TREND_UP", [100, -40] * 20), 30)
    updated = write_regime_fit(fit, str(tmp_path), 30)
    assert str(p) in updated
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["regime_fit"]["STRONG_TREND_UP"]["source"] == "ledger"


def test_write_skips_missing_file(tmp_path):
    fit = compute_regime_fit(_trades("Ghost", "RANGE", [10, -5] * 20), 30)
    assert write_regime_fit(fit, str(tmp_path), 30) == []

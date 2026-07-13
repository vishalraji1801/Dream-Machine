"""Strategy library wired into the regime router (strategies/*.yaml)."""
from src.regime import Regime
from src.strategy_meta import load_strategy_dir, param_set_for


def test_strategies_dir_loads_all():
    metas = load_strategy_dir("strategies")
    assert {"bb_mean_reversion", "donchian_trend_tsl", "supertrend", "orb_nifty"} <= set(metas)


def test_unvalidated_blocked_live_but_usable_in_backtest():
    # donchian is still validated:false — the governing rule blocks it in live/paper
    m = load_strategy_dir("strategies")["donchian_trend_tsl"]
    assert param_set_for(m, Regime.STRONG_TREND_UP, "live") is None
    assert param_set_for(m, Regime.STRONG_TREND_UP, "paper") is None
    # ...but is available in research/backtest
    assert param_set_for(m, Regime.STRONG_TREND_UP, "backtest") is not None


def test_supertrend_validated_for_paper():
    # supertrend was seeded + validated from the TCS walk-forward -> usable in paper
    m = load_strategy_dir("strategies")["supertrend"]
    assert param_set_for(m, Regime.STRONG_TREND_UP, "paper") is not None
    assert param_set_for(m, Regime.RANGE, "paper") is None       # disabled in range


def test_regime_enablement_matches_design():
    metas = load_strategy_dir("strategies")
    # mean-reversion disabled in strong trend; trend-follower disabled in range
    assert param_set_for(metas["bb_mean_reversion"], Regime.STRONG_TREND_UP, "backtest") is None
    assert param_set_for(metas["donchian_trend_tsl"], Regime.RANGE, "backtest") is None
    assert param_set_for(metas["donchian_trend_tsl"], Regime.STRONG_TREND_UP, "backtest") is not None

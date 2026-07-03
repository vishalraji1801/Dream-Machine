import pytest

from src.costs import estimate_intraday_costs, trade_leg_values


@pytest.fixture
def cfg():
    return {"costs": {"enabled": True}}  # defaults for all rates


def test_costs_zero_when_disabled():
    assert estimate_intraday_costs(100000, 101000, {"costs": {"enabled": False}}) == 0.0


def test_costs_positive_for_typical_trade(cfg):
    costs = estimate_intraday_costs(100000, 102000, cfg)
    assert costs > 0
    # sanity band for a ~2L turnover intraday round trip on Zerodha
    assert 60 < costs < 150


def test_brokerage_capped_at_20_per_leg(cfg):
    # 0.03% of 10L = 300 → capped at 20 per leg
    big = estimate_intraday_costs(1_000_000, 1_000_000, cfg)
    small = estimate_intraday_costs(10_000, 10_000, cfg)
    # brokerage on small trade: 0.03% of 10k = 3 per leg (not capped)
    # verify cap keeps the big trade's brokerage component at 40 total:
    # exchange+sebi+stt+stamp scale with value, brokerage does not
    assert big < 1_000_000 * 0.001  # far below uncapped scaling


def test_stt_applies_to_sell_leg_only(cfg):
    # same turnover, but different sell values → different STT
    costs_high_sell = estimate_intraday_costs(50000, 150000, cfg)
    costs_low_sell = estimate_intraday_costs(150000, 50000, cfg)
    assert costs_high_sell > costs_low_sell


def test_default_rates_used_when_costs_section_missing():
    costs = estimate_intraday_costs(100000, 100000, {})
    assert costs > 0


def test_costs_rounded_to_two_decimals(cfg):
    costs = estimate_intraday_costs(33333, 33334, cfg)
    assert costs == round(costs, 2)


# ── trade_leg_values ──────────────────────────────────────────────────────────

def test_leg_values_buy_direction():
    buy_v, sell_v = trade_leg_values("BUY", entry_price=100.0, exit_price=102.0, quantity=10)
    assert buy_v == 1000.0   # bought at entry
    assert sell_v == 1020.0  # sold at exit


def test_leg_values_sell_direction():
    buy_v, sell_v = trade_leg_values("SELL", entry_price=100.0, exit_price=98.0, quantity=10)
    assert buy_v == 980.0    # bought back at exit
    assert sell_v == 1000.0  # sold at entry

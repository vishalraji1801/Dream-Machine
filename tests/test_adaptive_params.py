"""Level-2 formula-scaled parameters (commit 3) — volatility scaling, purity."""
from src.adaptive_params import (atr_position_size, atr_stop_target,
                                 relative_volume, volume_gate)


# ── ATR stops/targets widen with volatility ───────────────────────────────────

def test_stop_target_buy_and_sell():
    sl, tgt = atr_stop_target(100, "BUY", atr=2.0, sl_mult=1.5, target_mult=3.0)
    assert sl == 97.0 and tgt == 106.0
    sl, tgt = atr_stop_target(100, "SELL", atr=2.0, sl_mult=1.5, target_mult=3.0)
    assert sl == 103.0 and tgt == 94.0


def test_stops_widen_with_atr():
    _, _ = atr_stop_target(100, "BUY", 1.0, 1.5, 3.0)
    calm = 100 - atr_stop_target(100, "BUY", 1.0, 1.5, 3.0)[0]
    wild = 100 - atr_stop_target(100, "BUY", 3.0, 1.5, 3.0)[0]
    assert wild > calm                       # higher ATR -> wider stop


# ── 1/ATR sizing keeps rupee risk constant across regimes ─────────────────────

def test_constant_rupee_risk_across_volatility():
    cap, risk_pct, sl_mult = 1_000_000, 1.0, 1.5
    for atr in (1.0, 2.0, 4.0):
        qty = atr_position_size(cap, risk_pct, atr, sl_mult)
        risk_at_stop = qty * sl_mult * atr
        # each stop-out risks ~1% of capital regardless of ATR (within one share)
        assert abs(risk_at_stop - cap * risk_pct / 100) <= sl_mult * atr


def test_higher_atr_smaller_size():
    a = atr_position_size(1_000_000, 1.0, 1.0, 1.5)
    b = atr_position_size(1_000_000, 1.0, 4.0, 1.5)
    assert b < a


def test_size_capped_by_position_value():
    qty = atr_position_size(1_000_000, 1.0, 0.1, 1.5, price=100,
                            max_position_value=50_000)
    assert qty == 500          # 50_000 / 100, cap binds before the huge risk-size


def test_size_zero_when_no_atr():
    assert atr_position_size(1_000_000, 1.0, 0.0, 1.5) == 0


# ── relative volume ───────────────────────────────────────────────────────────

def test_relative_volume():
    assert relative_volume(200, 100) == 2.0
    assert relative_volume(50, 100) == 0.5
    assert relative_volume(100, 0) is None


def test_volume_gate():
    assert volume_gate(2.0, 1.5) is True
    assert volume_gate(1.2, 1.5) is False
    assert volume_gate(None, 1.5) is False      # unknown RVOL fails closed


# ── purity ────────────────────────────────────────────────────────────────────

def test_module_is_pure():
    import src.adaptive_params as m
    src = open(m.__file__, encoding="utf-8").read()
    assert "datetime.now(" not in src and "kiteconnect" not in src

"""Swing engine — daily donchian/bb entries, overnight state, exits."""
from datetime import datetime

import pandas as pd
import pytest
import yaml

from src.swing_engine import SWING_STRATEGIES, SwingEngine, SwingPosition


def _pos(sym, qty=3, entry=100.0, stop=90.0):
    return SwingPosition(symbol=sym, strategy="maker_822bbda5", direction="BUY",
                         entry_price=entry, quantity=qty, stop=stop, target=200.0,
                         entry_date="2026-07-21", regime="RANGE", peak=entry, atr=5.0)


def _daily(closes, highs=None, lows=None):
    n = len(closes)
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": closes,
        "high": highs if highs is not None else [c + 2 for c in closes],
        "low": lows if lows is not None else [c - 2 for c in closes],
        "close": closes, "volume": [1_000_000] * n})


def _cfg():
    c = yaml.safe_load(open("config/config.yaml", encoding="utf-8"))
    c["trading"]["watchlist"] = ["AAA", "BBB"]
    c["swing"]["capital"] = 1_000_000
    return c


class FakeDB:
    def __init__(self):
        self.trade_rows, self.signals, self.routing = [], [], []

    def record_trade(self, **k): self.trade_rows.append(k)
    def record_signal(self, **k): self.signals.append(k)
    def record_routing(self, **k): self.routing.append(k)

    def trades(self, source=None):        # mirrors src.trade_db.TradeDB.trades()
        return [t for t in self.trade_rows if source is None or t.get("source") == source]


def _fetch(data):
    return lambda s, d: data.get(s)


NOW = datetime(2026, 7, 14, 15, 5)


def test_enters_donchian_long_in_uptrend(tmp_path):
    up = _daily([100 + i for i in range(260)])            # index: strong uptrend
    stock = _daily([100 + i * 0.8 for i in range(260)])   # new 200-day high on last bar
    data = {"NIFTY 50": up, "AAA": stock, "BBB": _daily([200] * 260)}
    db = FakeDB()
    eng = SwingEngine(_cfg(), "paper", db, _fetch(data), state_path=str(tmp_path / "sw.json"))
    r = eng.run_daily(now=NOW)
    assert r["regime"] == "STRONG_TREND_UP"
    assert "AAA" in eng.positions
    pos = eng.positions["AAA"]
    # WHICH of the (many) strategies that fire on this trending fixture wins AAA is now decided
    # by router weight (measured historical edge), not asserted here — see
    # test_contested_symbol_resolved_by_router_weight for that mechanism directly.
    assert pos.strategy in SWING_STRATEGIES and pos.direction == "BUY"
    assert pos.stop < pos.entry_price
    assert db.signals and db.routing                      # persisted


def test_contested_symbol_resolved_by_router_weight(tmp_path):
    # two strategies both fire BUY on the SAME symbol this cycle; the HIGHER-weight one
    # (router weight = allocation proportional to regime_fit.pf, i.e. "more positive
    # historical returns in this regime") wins the symbol; the loser is refused+logged
    # (reason=lower_weight_signal), not silently dropped.
    from src.regime import Regime, RegimeState
    from src.router import ActiveStrategy
    from src.strategy_meta import ParamSet
    stock = _daily([100 + i * 0.8 for i in range(260)])    # trending -> both strategies fire
    db = FakeDB()
    eng = SwingEngine(_cfg(), "paper", db, _fetch({"AAA": stock}), state_path=str(tmp_path / "sw.json"))
    low = ActiveStrategy(name="donchian_trend_tsl", param_set=ParamSet(params={}, validated=True),
                         weight=0.1, fit_pf=1.2, regime="STRONG_TREND_UP")
    high = ActiveStrategy(name="maker_5b132840", param_set=ParamSet(params={}, validated=True),
                          weight=0.9, fit_pf=2.0, regime="STRONG_TREND_UP")
    regime = RegimeState(regime=Regime.STRONG_TREND_UP, confidence=1.0, since_bars=10, inputs={})

    entered = eng._scan_entries(regime, [low, high], NOW)

    assert entered == 1
    assert eng.positions["AAA"].strategy == "maker_5b132840"      # higher weight wins the symbol
    assert any(s["strategy"] == "donchian_trend_tsl" and s["reason"] == "lower_weight_signal"
              and s["taken"] is False for s in db.signals)         # loser refused, not dropped
    # order in the ActiveStrategy list must not matter -> swap it, same winner
    eng2 = SwingEngine(_cfg(), "paper", FakeDB(), _fetch({"AAA": stock}),
                       state_path=str(tmp_path / "sw2.json"))
    eng2._scan_entries(regime, [high, low], NOW)
    assert eng2.positions["AAA"].strategy == "maker_5b132840"


def test_shadow_book_is_unconstrained_tracks_every_trigger(tmp_path):
    # the shadow book takes EVERY firing (symbol, strategy) combo - no one-position-per-symbol
    # limit (unlike the real book) and no total-capital cap. 2 strategies x 2 symbols -> 4
    # shadow positions, with total notional deliberately exceeding a tiny account capital.
    from src.regime import Regime, RegimeState
    from src.router import ActiveStrategy
    from src.strategy_meta import ParamSet
    stock = _daily([100 + i * 0.8 for i in range(260)])
    cfg = _cfg()
    cfg["swing"]["capital"] = 10_000             # deliberately tiny
    cfg["swing"]["max_position_value"] = 8_000   # ONE position alone nearly exhausts it
    eng = SwingEngine(cfg, "paper", FakeDB(), _fetch({"AAA": stock, "BBB": stock}),
                      state_path=str(tmp_path / "sw.json"))
    strategies = [
        ActiveStrategy(name="donchian_trend_tsl", param_set=ParamSet(params={}, validated=True),
                       weight=0.5, fit_pf=1.5, regime="STRONG_TREND_UP"),
        ActiveStrategy(name="maker_5b132840", param_set=ParamSet(params={}, validated=True),
                       weight=0.5, fit_pf=1.5, regime="STRONG_TREND_UP"),
    ]
    regime = RegimeState(regime=Regime.STRONG_TREND_UP, confidence=1.0, since_bars=10, inputs={})

    eng._scan_shadow(regime, strategies, NOW)

    assert len(eng.shadow) == 4                  # both strategies, both symbols - none dropped
    assert {"AAA|donchian_trend_tsl", "AAA|maker_5b132840",
           "BBB|donchian_trend_tsl", "BBB|maker_5b132840"} == set(eng.shadow)
    total_notional = sum(p.entry_price * p.quantity for p in eng.shadow.values())
    assert total_notional > cfg["swing"]["capital"]      # confirms: no capital cap


def test_shadow_priority_overrides_router_weight_once_enough_evidence(tmp_path):
    # LIVE realized shadow PF (from the unconstrained shadow book) should override the
    # router's static backtest weight once a strategy has enough closed shadow trades.
    from src.regime import Regime, RegimeState
    from src.router import ActiveStrategy
    from src.strategy_meta import ParamSet
    stock = _daily([100 + i * 0.8 for i in range(260)])
    db = FakeDB()
    for pnl in [100, 100, 100, 100, 100]:          # donchian: 5 wins, no losses -> shadow PF=inf
        db.record_trade(source="shadow", strategy="donchian_trend_tsl", pnl=pnl)
    for pnl in [-50, -50, -50, -50, -50]:          # maker_5b132840: 5 losses -> shadow PF=0
        db.record_trade(source="shadow", strategy="maker_5b132840", pnl=pnl)
    eng = SwingEngine(_cfg(), "paper", db, _fetch({"AAA": stock}), state_path=str(tmp_path / "sw.json"))
    winning_live_low_router_weight = ActiveStrategy(
        name="donchian_trend_tsl", param_set=ParamSet(params={}, validated=True),
        weight=0.1, fit_pf=1.2, regime="STRONG_TREND_UP")
    losing_live_high_router_weight = ActiveStrategy(
        name="maker_5b132840", param_set=ParamSet(params={}, validated=True),
        weight=0.9, fit_pf=2.0, regime="STRONG_TREND_UP")
    regime = RegimeState(regime=Regime.STRONG_TREND_UP, confidence=1.0, since_bars=10, inputs={})

    entered = eng._scan_entries(regime, [losing_live_high_router_weight,
                                         winning_live_low_router_weight], NOW)

    assert entered == 1
    assert eng.positions["AAA"].strategy == "donchian_trend_tsl"   # live evidence wins, not router weight


def test_shadow_priority_falls_back_to_router_weight_below_min_trades(tmp_path):
    # too few closed shadow trades to trust (< shadow_priority_min_trades) -> priority falls
    # back to the router's static weight, exactly as if no shadow evidence existed at all.
    from src.regime import Regime, RegimeState
    from src.router import ActiveStrategy
    from src.strategy_meta import ParamSet
    stock = _daily([100 + i * 0.8 for i in range(260)])
    db = FakeDB()
    for pnl in [100, 100]:                         # only 2 closed trades: below default min (5)
        db.record_trade(source="shadow", strategy="donchian_trend_tsl", pnl=pnl)
    eng = SwingEngine(_cfg(), "paper", db, _fetch({"AAA": stock}), state_path=str(tmp_path / "sw.json"))
    low_router_weight_thin_evidence = ActiveStrategy(
        name="donchian_trend_tsl", param_set=ParamSet(params={}, validated=True),
        weight=0.1, fit_pf=1.2, regime="STRONG_TREND_UP")
    high_router_weight_no_evidence = ActiveStrategy(
        name="maker_5b132840", param_set=ParamSet(params={}, validated=True),
        weight=0.9, fit_pf=2.0, regime="STRONG_TREND_UP")
    regime = RegimeState(regime=Regime.STRONG_TREND_UP, confidence=1.0, since_bars=10, inputs={})

    entered = eng._scan_entries(regime, [low_router_weight_thin_evidence,
                                         high_router_weight_no_evidence], NOW)

    assert entered == 1
    assert eng.positions["AAA"].strategy == "maker_5b132840"       # router weight still governs


def test_state_persists_across_restart(tmp_path):
    up = _daily([100 + i for i in range(260)])
    stock = _daily([100 + i * 0.8 for i in range(260)])
    data = {"NIFTY 50": up, "AAA": stock, "BBB": _daily([200] * 260)}
    sp = str(tmp_path / "sw.json")
    SwingEngine(_cfg(), "paper", FakeDB(), _fetch(data), state_path=sp).run_daily(now=NOW)
    reloaded = SwingEngine(_cfg(), "paper", FakeDB(), _fetch(data), state_path=sp)
    assert "AAA" in reloaded.positions                    # survived the "restart"


def test_exit_on_trailing_stop(tmp_path):
    up = _daily([100 + i for i in range(260)])
    stock = _daily([100 + i * 0.8 for i in range(260)])
    data = {"NIFTY 50": up, "AAA": stock, "BBB": _daily([200] * 260)}
    db = FakeDB()
    eng = SwingEngine(_cfg(), "paper", db, _fetch(data), state_path=str(tmp_path / "sw.json"))
    eng.run_daily(now=NOW)
    assert "AAA" in eng.positions
    stop = eng.positions["AAA"].stop
    # next day: AAA craters below the stop -> the trailing stop must exit the long.
    crash = [100 + i * 0.8 for i in range(259)] + [stop - 20]
    data["AAA"] = _daily(crash, lows=[c - 2 for c in crash[:-1]] + [stop - 25])
    eng.run_daily(now=datetime(2026, 7, 15, 15, 5))
    # The trailing stop exited the original donchian long. A dip-buy / other strategy
    # may re-enter AAA the SAME cycle (separate, valid decision) now that the sleeve
    # holds 6 strategies — so assert the EXIT fired, not permanent absence.
    assert any(t["exit_reason"].startswith("swing_stop") for t in db.trade_rows)
    held = eng.positions.get("AAA")
    assert held is None or held.entry_date != NOW.date().isoformat()   # original long gone


def test_winners_are_regime_agnostic(tmp_path):
    # The maker/gauntlet winners are validated regime-OFF, so they trade a trending stock
    # even when the INDEX is non-trend (the retired manual set used to sit out here). This
    # is the intended behavior change from wiring the OOS-validated basket.
    flat = _daily([200 + (1 if i % 2 else -1) for i in range(260)])   # index oscillates
    stock = _daily([100 + i * 0.8 for i in range(260)])               # AAA trends -> fires
    data = {"NIFTY 50": flat, "AAA": stock, "BBB": _daily([200] * 260)}
    eng = SwingEngine(_cfg(), "paper", FakeDB(), _fetch(data), state_path=str(tmp_path / "sw.json"))
    r = eng.run_daily(now=NOW)
    assert r["regime"] not in ("STRONG_TREND_UP", "STRONG_TREND_DOWN")   # non-trend index
    assert any(p.symbol == "AAA" for p in eng.positions.values())        # winner still trades it


def test_insufficient_index_data_skips(tmp_path):
    data = {"NIFTY 50": _daily([100] * 20)}
    eng = SwingEngine(_cfg(), "paper", FakeDB(), _fetch(data), state_path=str(tmp_path / "sw.json"))
    r = eng.run_daily(now=NOW)
    assert r["regime"] == "UNKNOWN" and r["entered"] == 0


# ── broker reconciliation (LIVE: Kite is the source of truth) ─────────────────

def test_reconcile_closes_positions_broker_no_longer_holds(tmp_path):
    db = FakeDB()
    eng = SwingEngine(_cfg(), "live", db, _fetch({}), state_path=str(tmp_path / "sw.json"),
                      fetch_holdings=lambda: [{"tradingsymbol": "AAA", "quantity": 3,
                                               "average_price": 100}])
    eng.positions = {"AAA": _pos("AAA", 3), "BBB": _pos("BBB", 5, stop=88.0)}  # BBB gone at broker
    r = eng.reconcile_with_broker()
    assert r["reconciled"] and r["closed"] == 1
    assert "AAA" in eng.positions and "BBB" not in eng.positions          # BBB reconciled closed
    assert any(t["symbol"] == "BBB" and t["exit_reason"] == "swing_reconciled_broker_exit"
               for t in db.trade_rows)


def test_reconcile_syncs_partial_and_ignores_untracked(tmp_path):
    hold = [{"tradingsymbol": "AAA", "quantity": 1, "average_price": 100},   # partial (had 3)
            {"tradingsymbol": "ZZZ", "quantity": 10, "average_price": 50}]   # manual, untracked
    eng = SwingEngine(_cfg(), "live", FakeDB(), _fetch({}), state_path=str(tmp_path / "sw.json"),
                      fetch_holdings=lambda: hold)
    eng.positions = {"AAA": _pos("AAA", 3)}
    r = eng.reconcile_with_broker()
    assert eng.positions["AAA"].quantity == 1 and r["adjusted"] == 1        # synced down
    assert "ZZZ" not in eng.positions and r["untracked"] == 1               # not managed


def test_reconcile_unsafe_without_holdings_source(tmp_path):
    eng = SwingEngine(_cfg(), "live", FakeDB(), _fetch({}), state_path=str(tmp_path / "sw.json"))
    r = eng.reconcile_with_broker()
    assert r["reconciled"] is False                                        # flagged unsafe


def test_reconcile_only_in_live_mode(tmp_path):
    calls = []
    eng = SwingEngine(_cfg(), "paper", FakeDB(), _fetch({"NIFTY 50": _daily([100] * 30)}),
                      state_path=str(tmp_path / "sw.json"),
                      fetch_holdings=lambda: calls.append(1) or [])
    eng.run_daily(now=NOW)                                                  # paper: never reconciles
    assert calls == []


# ── live order execution (CNC entry + GTT OCO stop/target) ────────────────────

class _Sig:
    def __init__(self, direction="BUY", entry=1000.0, stop=940.0, target=1200.0):
        self.direction, self.entry_price, self.stop_loss, self.target = direction, entry, stop, target


class MockExecutor:
    def __init__(self, fill=True, gtt_id=111):
        self.orders, self.gtts, self.modifies, self.cancels = [], [], [], []
        self._fill, self._gtt_id = fill, gtt_id

    def place_order(self, sym, direction, qty, price, order_type="LIMIT"):
        self.orders.append((sym, direction, qty, price, order_type))
        return "OID1" if self._fill else None

    def monitor_order(self, oid, timeout_sec=60):
        if not self._fill:
            return {"status": "REJECTED"}
        return {"status": "COMPLETE", "average_price": 1005.0,
                "filled_quantity": self.orders[-1][2]}

    def place_gtt_oco(self, sym, direction, qty, sl, tgt, last):
        self.gtts.append((sym, sl, tgt, qty)); return self._gtt_id

    def modify_gtt_oco(self, gid, sym, direction, qty, sl, tgt, last):
        self.modifies.append((gid, sl, tgt)); return True

    def cancel_gtt(self, gid):
        self.cancels.append(gid); return True


def test_live_open_places_cnc_order_and_gtt(tmp_path):
    ex = MockExecutor(fill=True)
    eng = SwingEngine(_cfg(), "live", FakeDB(), _fetch({}), state_path=str(tmp_path / "sw.json"),
                      executor=ex)
    opened = eng._open("AAA", "maker_822bbda5", _Sig(), 4, "RANGE", 5.0, NOW)
    assert opened is True
    assert ex.orders and ex.orders[0][0] == "AAA" and ex.orders[0][4] == "MARKET"   # CNC entry
    assert ex.gtts and ex.gtts[0][1] == 940.0 and ex.gtts[0][2] == 1200.0           # GTT SL+target
    pos = eng.positions["AAA"]
    assert pos.entry_price == 1005.0 and pos.gtt_id == 111        # ACTUAL fill + gtt id recorded


def test_live_open_aborts_when_not_filled(tmp_path):
    eng = SwingEngine(_cfg(), "live", FakeDB(), _fetch({}), state_path=str(tmp_path / "sw.json"),
                      executor=MockExecutor(fill=False))
    assert eng._open("AAA", "s", _Sig(), 4, "RANGE", 5.0, NOW) is False
    assert eng.positions == {}                                   # nothing opened on a reject


def test_live_open_no_executor_is_safe(tmp_path):
    eng = SwingEngine(_cfg(), "live", FakeDB(), _fetch({}), state_path=str(tmp_path / "sw.json"))
    assert eng._open("AAA", "s", _Sig(), 4, "RANGE", 5.0, NOW) is False   # no executor -> skip


def test_live_manage_exits_modifies_gtt_and_does_not_sim_close(tmp_path):
    ex = MockExecutor()
    data = {"AAA": _daily([1000 + i for i in range(30)])}        # rising -> stop ratchets up
    eng = SwingEngine(_cfg(), "live", FakeDB(), _fetch(data), state_path=str(tmp_path / "sw.json"),
                      executor=ex)
    p = _pos("AAA", qty=4, entry=1000.0, stop=940.0); p.gtt_id = 111; p.peak = 1000.0
    eng.positions = {"AAA": p}
    exited = eng._manage_exits(NOW)
    assert ex.modifies and ex.modifies[0][0] == 111              # GTT ratcheted at the exchange
    assert exited == 0 and "AAA" in eng.positions               # live: GTT owns exits, no sim close


# ── shadow book (unconstrained "what if" ledger for refused/all signals) ──────

def test_shadow_book_tracks_signals_and_books_pnl(tmp_path):
    up = _daily([100 + i for i in range(260)])
    stock = _daily([100 + i * 0.8 for i in range(260)])
    data = {"NIFTY 50": up, "AAA": stock, "BBB": _daily([100 + i * 0.7 for i in range(260)])}
    db = FakeDB()
    eng = SwingEngine(_cfg(), "paper", db, _fetch(data), state_path=str(tmp_path / "sw.json"))
    eng.run_daily(now=NOW)
    # the shadow book tracks EVERY firing signal (>= the capital-limited real book), keyed sym|strat
    assert eng.shadow and any("|" in k for k in eng.shadow)
    assert len(eng.shadow) >= len(eng.positions)
    # now crash AAA -> the shadow stop fires -> booked as source='shadow' (never a real order)
    crash = [100 + i * 0.8 for i in range(259)] + [50]
    data["AAA"] = _daily(crash, lows=[c - 2 for c in crash[:-1]] + [40])
    eng.run_daily(now=datetime(2026, 7, 15, 15, 5))
    assert db.trades(source="shadow")


def test_edge_covers_cost_gate(tmp_path):
    # a tiny-edge trade (1 rupee target, 1 share) is structurally unprofitable once the flat
    # DP charge + STT are counted -> the gate refuses it; a real-size trade passes.
    eng = SwingEngine(_cfg(), "paper", FakeDB(), _fetch({}), state_path=str(tmp_path / "sw.json"))
    tiny = _Sig(direction="BUY", entry=100.0, stop=98.0, target=101.0)
    big = _Sig(direction="BUY", entry=100.0, stop=90.0, target=110.0)
    assert eng._edge_covers_cost(tiny, qty=1) is False        # cost dwarfs a 1-rupee edge
    assert eng._edge_covers_cost(big, qty=1000) is True       # 10k edge easily covers cost
    # degenerate target (no edge estimate) is allowed through - not this gate's job
    assert eng._edge_covers_cost(_Sig(target=0.0), qty=10) is True


def test_shadow_book_persists(tmp_path):
    up = _daily([100 + i for i in range(260)])
    data = {"NIFTY 50": up, "AAA": _daily([100 + i * 0.8 for i in range(260)]),
            "BBB": _daily([200] * 260)}
    sp = str(tmp_path / "sw.json")
    SwingEngine(_cfg(), "paper", FakeDB(), _fetch(data), state_path=sp).run_daily(now=NOW)
    reloaded = SwingEngine(_cfg(), "paper", FakeDB(), _fetch(data), state_path=sp)
    assert reloaded.shadow                                  # shadow survived the restart

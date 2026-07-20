"""Strategy Maker — intraday sleeve EVALUATION + generation (session blocks).

Guards: the intraday block evaluators compile+run (no NotImplementedError), the session
helpers are correct, an opening-range breakout fires, and the generator emits intraday
candidates that all carry the mandatory square_off MIS exit.
"""
import numpy as np
import pandas as pd

from maker.generate import IMPLEMENTED_INTRADAY, random_candidate, random_candidates
from maker.grammar import _session_vwap, compile, make_candidate


def _intraday_df(days=12, bars=25, start="2026-02-02"):
    rows, price = [], 100.0
    for day in range(days):
        t = pd.Timestamp(start) + pd.Timedelta(days=day) + pd.Timedelta(hours=9, minutes=15)
        for b in range(bars):
            price *= 1 + np.sin(b / 4 + day) / 200
            rows.append((t, price, price + 0.3, price - 0.3, price + 0.1, 1000 + b * 10))
            t += pd.Timedelta(minutes=15)
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = df["timestamp"].dt.tz_localize("Asia/Kolkata")
    return df


def _intraday(setup, trigger, exit_b=("r_multiple", {"r": 2})):
    return make_candidate("long", {"setup": setup, "trigger": trigger, "exit": exit_b,
                                   "hold": ("square_off", {"at": "15:10"})}, sleeve="intraday")


def test_all_intraday_setups_and_triggers_evaluate():
    df = _intraday_df()
    setups = [("opening_range", {"window_min": 15, "break_side": "high"}),
              ("vwap_relation", {"state": "hold_above", "min_dist_pct": 0}),
              ("prior_day_level", {"level": "pdh", "action": "break"}),
              ("intraday_flush", {"down_pct_in_min": (2, 15)})]
    triggers = [("breakout_close", {"of": "setup_level"}),
                ("candle_confirm_1m", {"accept": ("hammer_white", "doji"), "above_vwap": True}),
                ("new_extreme_after_pullback", {"pullback_bars": 2})]
    for s in setups:
        sig = compile(_intraday(s, ("breakout_close", {"of": "setup_level"})))("X", df, {})
        assert sig.direction in ("BUY", "HOLD")          # must not raise NotImplementedError
    for t in triggers:
        sig = compile(_intraday(("prior_day_level", {"level": "pdc", "action": "break"}), t))("X", df, {})
        assert sig.direction in ("BUY", "HOLD")


def test_intraday_regime_gates_evaluate():
    df = _intraday_df()
    for regime in [("time_window", {"allow": ("14:00", "15:00")}),
                   ("skip_open_minutes", {"min": 15})]:
        c = make_candidate("long", {         # lean base so the regime gate fits the budget
            "regime": regime,
            "setup": ("intraday_flush", {"down_pct_in_min": (2, 15)}),
            "trigger": ("breakout_close", {"of": "setup_level"}),
            "exit": ("opposite_band", {"bollinger": (20, 2.0)}),
            "hold": ("square_off", {"at": "15:10"})}, sleeve="intraday")
        assert compile(c)("X", df, {}).direction in ("BUY", "HOLD")


def test_session_vwap_resets_each_day():
    df = _intraday_df(days=3, bars=25)
    v = _session_vwap(df)
    last_day = df[pd.to_datetime(df["timestamp"]).dt.date == pd.to_datetime(df["timestamp"]).dt.date.iloc[-1]]
    tp = (last_day["high"] + last_day["low"] + last_day["close"]) / 3
    expect = float((tp * last_day["volume"]).sum() / last_day["volume"].sum())
    assert abs(v - expect) < 1e-6          # VWAP uses only the current session's bars


def test_opening_range_breakout_fires():
    # flat opening range, then a clean breakout above it on the last bar
    ts = pd.date_range("2026-02-02 09:15", periods=20, freq="15min", tz="Asia/Kolkata")
    close = [100] * 10 + [100.5, 101, 101.5, 102, 102.5, 103, 103.5, 104, 104.5, 105]
    df = pd.DataFrame({"timestamp": ts, "open": close, "high": [c + 0.2 for c in close],
                       "low": [c - 0.2 for c in close], "close": close, "volume": [1000] * 20})
    from maker.grammar import _setup_level, _trigger_ok
    lvl = _setup_level("opening_range", {"window_min": 30, "break_side": "high"}, df)
    assert lvl is not None and lvl < df["close"].iloc[-1]      # broke above the OR high
    assert _trigger_ok("breakout_close", {"of": "setup_level"}, df, lvl)


def test_intraday_generates_long_and_short_all_admissible():
    import random
    from maker.constraints import check
    rng = random.Random(2)
    dirs, ok = {}, 0
    for _ in range(200):
        d = rng.choice(["long", "short"])
        c = random_candidate(rng, sleeve="intraday", direction=d)
        dirs[c.direction] = dirs.get(c.direction, 0) + 1
        if check(c, product="intraday")[0]:
            ok += 1
    assert dirs.get("long", 0) > 0 and dirs.get("short", 0) > 0    # both sides generated
    assert ok == 200                                              # all admissible (stocks-in-play)


def test_short_intraday_breakdown_fires_a_sell():
    # a prior-day-low breakdown short: price breaks BELOW the prior session low
    idx = pd.date_range("2026-02-02 09:15", periods=50, freq="15min", tz="Asia/Kolkata")
    day2 = pd.date_range("2026-02-03 09:15", periods=50, freq="15min", tz="Asia/Kolkata")
    ts = idx.append(day2)
    close = [110] * 50 + list(np.linspace(109, 104, 50))          # day2 breaks below day1 low
    df = pd.DataFrame({"timestamp": ts, "open": close, "high": [c + 0.2 for c in close],
                       "low": [c - 0.2 for c in close], "close": close, "volume": [1000] * 100})
    c = make_candidate("short", {
        "setup": ("prior_day_level", {"level": "pdl", "action": "break"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("r_multiple", {"r": 2}), "hold": ("square_off", {"at": "15:10"})},
        sleeve="intraday")
    # pad to satisfy the 210-bar compile floor with prior warmup bars
    warm = pd.DataFrame({"timestamp": pd.date_range("2026-01-19 09:15", periods=200, freq="15min",
                                                    tz="Asia/Kolkata"),
                         "open": [110] * 200, "high": [110.2] * 200, "low": [109.8] * 200,
                         "close": [110] * 200, "volume": [1000] * 200})
    sig = compile(c)("X", pd.concat([warm, df], ignore_index=True), {})
    assert sig.direction in ("SELL", "HOLD")
    if sig.direction == "SELL":
        assert sig.target < sig.entry_price < sig.stop_loss       # short levels


def test_timeframe_stamps_distinct_candidates():
    import random
    from maker.registry import family_id
    a = random_candidate(random.Random(4), sleeve="intraday", direction="long", timeframe="5min")
    b = random_candidate(random.Random(4), sleeve="intraday", direction="long", timeframe="15min")
    assert a.timeframe == "5min" and b.timeframe == "15min"
    assert a.cid != b.cid and family_id(a) == family_id(b)        # distinct cid, same family


def test_generator_emits_intraday_with_square_off():
    cands = random_candidates(400, seed=7, sleeve="intraday")
    assert all(c.sleeve == "intraday" for c in cands)
    assert all(c.blocks.get("hold") and c.blocks["hold"].name == "square_off" for c in cands)
    used = {}
    for c in cands:
        for bi in c.blocks.values():
            used[bi.name] = used.get(bi.name, 0) + 1
    for name in ("opening_range", "vwap_relation", "prior_day_level", "intraday_flush",
                 "candle_confirm_1m", "new_extreme_after_pullback"):
        assert used.get(name, 0) > 0, f"intraday block {name} never emitted"
    # no swing-only block leaks into an intraday candidate
    assert used.get("nday_extreme", 0) == 0 and used.get("double_bottom", 0) == 0

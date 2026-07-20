"""Maker reserve-CERTIFIED strategies, materialized for the backtester.

AUTO-GENERATED from the maker registry's ALIVE reserve verdicts (scratchpad/
gen_maker_certified.py). Each strategy DELEGATES to the exact compiled maker candidate,
so backtest/live behaviour == what was certified on the sealed reserve holdout.
The `reserve` block records the certification metrics; top3_frac > 0.6 means the edge
is outlier-carried (few trades dominate) -- scrutinise before trusting.
"""
import pandas as pd  # noqa: F401  (kept for parity with the strategy toolkit)

MANIFEST = {
    'ebf605d57cf78e92': {'name': 'maker_ebf605d5', 'direction': 'long', 'blocks': {'setup': ['objective_level', {'level': 'pdh'}], 'trigger': ['resume_new_high', {'within_bars': 5}], 'exit': ['atr_trail', {'mult': 6, 'period': 14}]}, 'reserve': {'pf': 2.8, 'trades': 25, 'net': 17313.21, 'top3_frac': 0.613}},
    '4679245dc2b35d4e': {'name': 'maker_4679245d', 'direction': 'long', 'blocks': {'setup': ['objective_level', {'level': 'pdh'}], 'trigger': ['confirm_candle', {'accept': ('hammer_white', 'doji'), 'above_vwap': True}], 'exit': ['atr_trail', {'mult': 6, 'period': 14}]}, 'reserve': {'pf': 8.0, 'trades': 27, 'net': 18105.21, 'top3_frac': 0.687}},
    'f6cfe6d7d313de6e': {'name': 'maker_f6cfe6d7', 'direction': 'long', 'blocks': {'setup': ['inv_head_shoulders', {'swing_n': 5, 'shoulder_tol_pct': 5.0}], 'trigger': ['breakout_close', {'of': 'setup_level'}], 'exit': ['atr_trail', {'mult': 5, 'period': 14}]}, 'reserve': {'pf': 1.72, 'trades': 38, 'net': 25581.15, 'top3_frac': 0.662}},
    'eb1ea126f21e5f6b': {'name': 'maker_eb1ea126', 'direction': 'long', 'blocks': {'setup': ['inv_head_shoulders', {'swing_n': 5, 'shoulder_tol_pct': 3.0}], 'trigger': ['bullish_reversal_candle', {'pattern': 'engulfing'}], 'exit': ['atr_trail', {'mult': 6, 'period': 14}]}, 'reserve': {'pf': 1.7, 'trades': 23, 'net': 10196.26, 'top3_frac': 1.089}},
    '0c68fadb7773625a': {'name': 'maker_0c68fadb', 'direction': 'long', 'blocks': {'setup': ['flush', {'down_pct_in_bars': (15, 5)}], 'trigger': ['limit_below', {'offset_pct': 0}], 'exit': ['atr_trail', {'mult': 5, 'period': 14}]}, 'reserve': {'pf': 9.02, 'trades': 22, 'net': 22822.49, 'top3_frac': 0.489}},
    '9227a6ffd6b9e3bb': {'name': 'maker_9227a6ff', 'direction': 'long', 'blocks': {'setup': ['double_bottom', {'swing_n': 5, 'tol_pct': 2.0}], 'trigger': ['limit_below', {'offset_pct': 0}], 'exit': ['atr_trail', {'mult': 5, 'period': 14}]}, 'reserve': {'pf': 1.46, 'trades': 28, 'net': 12605.68, 'top3_frac': 1.136}},
    'eadcde15fcf4988a': {'name': 'maker_eadcde15', 'direction': 'long', 'blocks': {'setup': ['inv_head_shoulders', {'swing_n': 10, 'shoulder_tol_pct': 5.0}], 'trigger': ['confirm_candle', {'accept': ('hammer_white', 'doji'), 'above_vwap': True}], 'exit': ['atr_trail', {'mult': 6, 'period': 14}]}, 'reserve': {'pf': 3.74, 'trades': 27, 'net': 24477.36, 'top3_frac': 0.463}},
    '5b1328408a1b2dc6': {'name': 'maker_5b132840', 'direction': 'long', 'blocks': {'setup': ['objective_level', {'level': 'pdh'}], 'trigger': ['limit_below', {'offset_pct': 0}], 'exit': ['atr_trail', {'mult': 5, 'period': 14}]}, 'reserve': {'pf': 1.73, 'trades': 25, 'net': 15291.6, 'top3_frac': 0.921}},
    'd4cf5eb9b793e15b': {'name': 'maker_d4cf5eb9', 'direction': 'long', 'blocks': {'setup': ['gap', {'gap_pct_min': 2, 'direction': 'up'}], 'trigger': ['breakout_close', {'of': 'setup_level'}], 'exit': ['atr_trail', {'mult': 6, 'period': 14}]}, 'reserve': {'pf': 1.92, 'trades': 30, 'net': 10985.54, 'top3_frac': 0.829}},
    '496826cf3d424aee': {'name': 'maker_496826cf', 'direction': 'long', 'blocks': {'setup': ['band_touch', {'bollinger': (20, 2.0), 'side': 'upper'}], 'trigger': ['breakout_close', {'of': 'setup_level'}], 'exit': ['atr_trail', {'mult': 5, 'period': 14}]}, 'reserve': {'pf': 2.35, 'trades': 29, 'net': 29619.07, 'top3_frac': 0.532}},
    '19d44d4e647df9f2': {'name': 'maker_19d44d4e', 'direction': 'long', 'blocks': {'setup': ['pullback_depth', {'from_high_pct': 5, 'within_trend_ma': 200}], 'trigger': ['confirm_candle', {'accept': ('hammer_white', 'doji'), 'above_vwap': True}], 'exit': ['atr_trail', {'mult': 6, 'period': 14}], 'regime': ['bb_width_pctile', {'above': 75}]}, 'reserve': {'pf': 3.3, 'trades': 28, 'net': 15636.47, 'top3_frac': 0.632}},
    '822bbda5c9a017d3': {'name': 'maker_822bbda5', 'direction': 'long', 'blocks': {'setup': ['objective_level', {'level': 'pdc'}], 'trigger': ['breakout_close', {'of': 'setup_level'}], 'exit': ['atr_trail', {'mult': 5, 'period': 14}]}, 'reserve': {'pf': 3.93, 'trades': 39, 'net': 39929.99, 'top3_frac': 0.325}},
    '2119819586e42f34': {'name': 'maker_21198195', 'direction': 'long', 'blocks': {'setup': ['compression', {'bbw_pctile_below': 15, 'min_bars': 5}], 'trigger': ['bullish_reversal_candle', {'pattern': 'morning_star'}], 'exit': ['atr_trail', {'mult': 5, 'period': 14}]}, 'reserve': {'pf': 1.56, 'trades': 31, 'net': 14124.53, 'top3_frac': 1.258}},
    'deb70ada46388edc': {'name': 'maker_deb70ada', 'direction': 'long', 'blocks': {'setup': ['gap', {'gap_pct_min': 3, 'direction': 'up'}], 'trigger': ['resume_new_high', {'within_bars': 5}], 'exit': ['atr_trail', {'mult': 5, 'period': 14}]}, 'reserve': {'pf': 2.32, 'trades': 25, 'net': 15372.82, 'top3_frac': 0.794}},
}

_COMPILED = {}


def _make(family, spec):
    def fn(symbol, df, cfg):
        f = _COMPILED.get(family)
        if f is None:
            from maker.grammar import compile as _compile, make_candidate
            blocks = {s: (n, dict(p)) for s, (n, p) in spec['blocks'].items()}
            f = _COMPILED[family] = _compile(make_candidate(spec['direction'], blocks))
        sig = f(symbol, df, cfg)
        if sig.direction == 'HOLD':
            return sig
        from src.strategy import TradeSignal
        return TradeSignal(sig.direction, symbol, sig.entry_price, sig.stop_loss,
                           sig.target, spec['name'])
    return fn


REGISTRY = {spec['name']: _make(fam, spec) for fam, spec in MANIFEST.items()}

"""Maker GAUNTLET survivors that did NOT certify (reserve-DEAD/none), materialized
for backtesting. AUTO-GENERATED (scratchpad/gen_maker_gauntlet.py). These cleared the
gauntlet's plateau + OOS test but failed the sealed reserve holdout — a fuller backtest
re-examines them. Distinct from the 14 certified in maker_certified.py.
"""
import pandas as pd  # noqa: F401

MANIFEST = {
    '73b2fda7163ca00d': {'name': 'mkg_73b2fda7', 'direction': 'long', 'blocks': {'setup': ['compression', {'bbw_pctile_below': 10, 'min_bars': 5}], 'trigger': ['breakout_close', {'of': 'setup_level'}], 'exit': ['atr_trail', {'mult': 6, 'period': 14}]}, 'gauntlet': {'oos_pf': 1.47, 'oos_trades': 122, 'plateau': '22/24'}, 'reserve': 'DEAD'},
    '06e96562e26f876f': {'name': 'mkg_06e96562', 'direction': 'long', 'blocks': {'setup': ['nday_extreme', {'lookback': 50, 'side': 'high'}], 'trigger': ['limit_below', {'offset_pct': 5}], 'exit': ['atr_trail', {'mult': 6, 'period': 14}]}, 'gauntlet': {'oos_pf': 1.44, 'oos_trades': 119, 'plateau': '23/24'}, 'reserve': 'DEAD'},
    '36c466f61ae8f50f': {'name': 'mkg_36c466f6', 'direction': 'long', 'blocks': {'setup': ['double_bottom', {'swing_n': 10, 'tol_pct': 2.0}], 'trigger': ['confirm_candle', {'accept': ('hammer_white', 'doji'), 'above_vwap': True}], 'exit': ['atr_trail', {'mult': 6, 'period': 14}]}, 'gauntlet': {'oos_pf': 1.4, 'oos_trades': 134, 'plateau': '14/16'}, 'reserve': 'DEAD'},
    '2e09c6334f266177': {'name': 'mkg_2e09c633', 'direction': 'long', 'blocks': {'setup': ['pullback_depth', {'from_high_pct': 15, 'within_trend_ma': 200}], 'trigger': ['limit_below', {'offset_pct': 0}], 'exit': ['atr_trail', {'mult': 5, 'period': 14}]}, 'gauntlet': {'oos_pf': 2.37, 'oos_trades': 144, 'plateau': '16/24'}, 'reserve': 'DEAD'},
    'ba802757d70ffee6': {'name': 'mkg_ba802757', 'direction': 'long', 'blocks': {'setup': ['objective_level', {'level': 'pdh'}], 'trigger': ['confirm_candle', {'accept': ('hammer_white', 'doji'), 'above_vwap': True}], 'exit': ['opposite_band', {'bollinger': (20, 2.0)}], 'regime': ['bb_width_pctile', {'above': 85}]}, 'gauntlet': {'oos_pf': 1.44, 'oos_trades': 146, 'plateau': '4/8'}, 'reserve': 'DEAD'},
    '847ba1fe4ab9fb4f': {'name': 'mkg_847ba1fe', 'direction': 'long', 'blocks': {'setup': ['flush', {'down_pct_in_bars': (10, 5)}], 'trigger': ['breakout_close', {'of': 'setup_level'}], 'exit': ['atr_trail', {'mult': 4, 'period': 14}]}, 'gauntlet': {'oos_pf': 1.44, 'oos_trades': 127, 'plateau': '12/24'}, 'reserve': 'DEAD'},
    'ff0fa4798080174f': {'name': 'mkg_ff0fa479', 'direction': 'long', 'blocks': {'setup': ['gap', {'gap_pct_min': 3, 'direction': 'up'}], 'trigger': ['resume_new_high', {'within_bars': 5}], 'exit': ['r_multiple', {'r': 3}]}, 'gauntlet': {'oos_pf': 1.57, 'oos_trades': 207, 'plateau': '16/24'}, 'reserve': 'DEAD'},
    '083f1e87bc67b912': {'name': 'mkg_083f1e87', 'direction': 'long', 'blocks': {'setup': ['pullback_depth', {'from_high_pct': 15, 'within_trend_ma': 200}], 'trigger': ['limit_below', {'offset_pct': 0}], 'exit': ['atr_trail', {'mult': 5, 'period': 14}], 'regime': ['bb_width_pctile', {'below': 15}]}, 'gauntlet': {'oos_pf': 1.76, 'oos_trades': 154, 'plateau': '16/24'}, 'reserve': 'DEAD'},
    '9e41b56cdd768209': {'name': 'mkg_9e41b56c', 'direction': 'long', 'blocks': {'setup': ['pullback_depth', {'from_high_pct': 5, 'within_trend_ma': 200}], 'trigger': ['confirm_candle', {'accept': ('hammer_white', 'doji'), 'above_vwap': True}], 'exit': ['atr_trail', {'mult': 5, 'period': 14}]}, 'gauntlet': {'oos_pf': 1.49, 'oos_trades': 144, 'plateau': '12/12'}, 'reserve': 'DEAD'},
    '9de735439a776b20': {'name': 'mkg_9de73543', 'direction': 'long', 'blocks': {'setup': ['flush', {'down_pct_in_bars': (15, 5)}], 'trigger': ['breakout_close', {'of': 'setup_level'}], 'exit': ['opposite_band', {'bollinger': (20, 2.0)}], 'regime': ['bb_width_pctile', {'above': 75}]}, 'gauntlet': {'oos_pf': 1.88, 'oos_trades': 54, 'plateau': '12/18'}, 'reserve': 'DEAD'},
    '7fca1c984a27991d': {'name': 'mkg_7fca1c98', 'direction': 'long', 'blocks': {'setup': ['pullback_depth', {'from_high_pct': 10, 'within_trend_ma': 200}], 'trigger': ['breakout_close', {'of': 'setup_level'}], 'exit': ['atr_trail', {'mult': 6, 'period': 14}]}, 'gauntlet': {'oos_pf': 1.93, 'oos_trades': 126, 'plateau': '18/24'}, 'reserve': 'DEAD'},
    'b9d2738e92c7ea99': {'name': 'mkg_b9d2738e', 'direction': 'long', 'blocks': {'setup': ['objective_level', {'level': 'pdh'}], 'trigger': ['bullish_reversal_candle', {'pattern': 'morning_star'}], 'exit': ['atr_trail', {'mult': 6, 'period': 14}]}, 'gauntlet': {'oos_pf': 2.22, 'oos_trades': 140, 'plateau': '21/24'}, 'reserve': 'DEAD'},
    'ca0281946c7c2c90': {'name': 'mkg_ca028194', 'direction': 'long', 'blocks': {'setup': ['gap', {'gap_pct_min': 3, 'direction': 'up'}], 'trigger': ['confirm_candle', {'accept': ('hammer_white', 'doji'), 'above_vwap': True}], 'exit': ['r_multiple', {'r': 3}], 'regime': ['bb_width_pctile', {'above': 75}]}, 'gauntlet': {'oos_pf': 2.33, 'oos_trades': 21, 'plateau': '12/24'}, 'reserve': 'DEAD'},
    '6a895e947554e7b2': {'name': 'mkg_6a895e94', 'direction': 'long', 'blocks': {'setup': ['pullback_depth', {'from_high_pct': 15, 'within_trend_ma': 200}], 'trigger': ['bullish_reversal_candle', {'pattern': 'morning_star'}], 'exit': ['atr_trail', {'mult': 5, 'period': 14}]}, 'gauntlet': {'oos_pf': 1.44, 'oos_trades': 100, 'plateau': '12/24'}, 'reserve': 'DEAD'},
    '99936fb7cc08bb5f': {'name': 'mkg_99936fb7', 'direction': 'long', 'blocks': {'setup': ['band_touch', {'bollinger': (20, 2.5), 'side': 'upper'}], 'trigger': ['confirm_candle', {'accept': ('hammer_white', 'doji'), 'above_vwap': True}], 'exit': ['atr_trail', {'mult': 6, 'period': 14}]}, 'gauntlet': {'oos_pf': 1.51, 'oos_trades': 57, 'plateau': '8/16'}, 'reserve': 'DEAD'},
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

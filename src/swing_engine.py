"""
Swing engine — the daily / positional sleeve (donchian + bb), integrated into the bot.

Runs ONCE a day near the close on DAILY candles, holds CNC positions overnight (its
own book, persisted across restarts), and manages exits on the daily bar:
  - donchian: a 6x ATR trailing stop that ratchets each day,
  - bb:       target = the mean (middle band), plus a disaster stop.

It reuses the pure pieces — the strategies, the regime classifier, the router
(regime-gates donchian to trends / bb to range) and the ledger. Separate capital
book so it never collides with the intraday bot's margin. Paper mode simulates
fills and records to the ledger; live order placement (CNC + GTT stops) is a
follow-up — the paper path is what runs today.

`fetch_daily(symbol, lookback_days) -> DataFrame|None` is injected for testability.
"""
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable, Optional

from src.logger import get_logger
from src.market_state import compute_market_state
from src.regime import RegimeConfig, classify
from src.router import PremarketAllocation, RouterConfig, route, routing_records
from src.strategy import _atr, generate_signal
from src.strategy_meta import load_strategy_dir

logger = get_logger("swing_engine")

SWING_STRATEGIES = ("donchian_trend_tsl", "bb_mean_reversion",
                    "volatility_contraction_breakout", "double_reversal",
                    "index_dip_reversion", "ma_pullback", "abcd_pattern")


@dataclass
class SwingPosition:
    symbol: str
    strategy: str
    direction: str
    entry_price: float
    quantity: int
    stop: float
    target: float
    entry_date: str
    regime: str
    peak: float          # highest close (long) / lowest (short) since entry — for trailing
    atr: float


class SwingEngine:
    def __init__(self, cfg: dict, mode: str, db, fetch_daily: Callable,
                 index_symbol: str = "NIFTY 50",
                 state_path: str = os.path.join("logs", "swing_state.json"),
                 strategies_dir: str = "strategies"):
        self.cfg = cfg
        self.mode = mode
        self.db = db
        self.fetch_daily = fetch_daily
        self.index_symbol = index_symbol
        self.state_path = state_path

        s = cfg.get("swing", {})
        self.capital = s.get("capital", 500_000)
        self.risk_pct = s.get("risk_pct", 1.0)
        self.max_positions = s.get("max_positions", 5)
        self.atr_mult = s.get("atr_stop_mult", 6.0)
        self.lookback_days = s.get("lookback_days", 320)
        self.max_position_pct = s.get("max_position_pct", 20.0)

        metas = load_strategy_dir(strategies_dir)
        self.metas = [m for n, m in metas.items() if n in SWING_STRATEGIES]
        rc = cfg.get("regime_daily", cfg.get("regime", {}))
        self.regime_cfg = RegimeConfig(**{k: v for k, v in rc.items()
                                          if k in RegimeConfig.__dataclass_fields__})
        self.ms_cfg = cfg.get("market_state", {})
        r = cfg.get("router", {})
        self.router_cfg = RouterConfig(mode=mode, min_fit_pf=r.get("min_fit_pf", 1.0),
                                       min_trades=r.get("min_trades", 30))
        self.premarket = PremarketAllocation(ceiling=1.0)

        self.positions: dict = {}
        self._prev_regime = None
        self.load_state()

    # ── once-a-day run ────────────────────────────────────────────────────────

    def run_daily(self, now: Optional[datetime] = None) -> dict:
        now = now or datetime.now()
        idx = self.fetch_daily(self.index_symbol, self.lookback_days)
        if idx is None or len(idx) < 60:
            logger.warning("swing: insufficient index daily data — skipping run")
            return {"regime": "UNKNOWN", "entered": 0, "exited": 0, "open": len(self.positions)}

        state = compute_market_state(idx, self.ms_cfg)
        self._prev_regime = classify(state, self._prev_regime, self.regime_cfg)
        regime = self._prev_regime

        exited = self._manage_exits(now)
        active = route(regime, self.metas, self.premarket, self.router_cfg)
        entered = self._scan_entries(regime, active, now)
        self.save_state()

        if self.db is not None:
            try:
                self.db.record_routing(source=self.mode, regime=regime.regime.value,
                                       confidence=regime.confidence,
                                       active=routing_records(active),
                                       config_version="swing")
            except Exception as exc:
                logger.error(f"swing: routing persist failed — {exc}")

        names = [f"{a.name}:{a.weight:.2f}" for a in active]
        logger.warning(f"swing: regime={regime.regime.value} conf={regime.confidence:.2f} "
                       f"active=[{', '.join(names) or 'NONE'}] exited={exited} "
                       f"entered={entered} open={len(self.positions)}")
        return {"regime": regime.regime.value, "entered": entered, "exited": exited,
                "open": len(self.positions)}

    # ── exits (managed on the daily bar) ──────────────────────────────────────

    def _manage_exits(self, now: datetime) -> int:
        exited = 0
        for sym in list(self.positions):
            pos = self.positions[sym]
            df = self.fetch_daily(sym, self.lookback_days)
            if df is None or df.empty:
                continue
            bar = df.iloc[-1]
            high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])
            atr = _atr(df, 14) or pos.atr

            if pos.strategy == "donchian_trend_tsl":       # ratchet the trailing stop
                prev_stop = pos.stop
                if pos.direction == "BUY":
                    pos.peak = max(pos.peak, close)
                    pos.stop = max(pos.stop, pos.peak - self.atr_mult * atr)
                else:
                    pos.peak = min(pos.peak, close)
                    pos.stop = min(pos.stop, pos.peak + self.atr_mult * atr)
                # Kite has no native trailing GTT — when the stop moves, the bot must
                # MODIFY the exchange GTT itself (live only; paper simulates the exit).
                executor = getattr(self, "executor", None)   # None until live exec is wired
                if (self.mode == "live" and pos.stop != prev_stop and executor is not None):
                    try:
                        executor.modify_gtt(pos.symbol, pos.direction,
                                            pos.quantity, round(pos.stop, 2), pos.target)
                    except Exception as exc:
                        logger.error(f"swing: GTT modify failed for {pos.symbol} — {exc}")

            exit_price = reason = None
            if pos.direction == "BUY":
                if low <= pos.stop:
                    exit_price, reason = pos.stop, "stop"
                elif pos.target and high >= pos.target:
                    exit_price, reason = pos.target, "target"
            else:
                if high >= pos.stop:
                    exit_price, reason = pos.stop, "stop"
                elif pos.target and low <= pos.target:
                    exit_price, reason = pos.target, "target"
            if exit_price is not None:
                self._close(pos, exit_price, reason, now)
                exited += 1
        return exited

    # ── entries ───────────────────────────────────────────────────────────────

    def _scan_entries(self, regime, active: list, now: datetime) -> int:
        if not active or len(self.positions) >= self.max_positions:
            return 0
        entered = 0
        for sym in self.cfg["trading"]["watchlist"]:
            if len(self.positions) >= self.max_positions:
                break
            if sym in self.positions:
                continue
            df = self.fetch_daily(sym, self.lookback_days)
            if df is None or len(df) < 210:
                continue
            for a in active:
                scfg = {**self.cfg["strategy"], **a.param_set.params, "name": a.name}
                sig = generate_signal(sym, df, scfg)
                if sig.direction == "HOLD":
                    continue
                stop_dist = abs(sig.entry_price - sig.stop_loss)
                if stop_dist <= 0:
                    continue
                risk_amt = self.capital * self.risk_pct / 100 * a.weight
                qty = int(risk_amt / stop_dist)
                qty = min(qty, int(self.capital * self.max_position_pct / 100 / sig.entry_price))
                if qty <= 0:
                    continue
                self._open(sym, a.name, sig, qty, regime.regime.value, _atr(df, 14), now)
                entered += 1
                break
        return entered

    def _open(self, sym, strat, sig, qty, regime, atr, now):
        self.positions[sym] = SwingPosition(
            symbol=sym, strategy=strat, direction=sig.direction,
            entry_price=sig.entry_price, quantity=qty, stop=sig.stop_loss,
            target=sig.target, entry_date=now.date().isoformat(), regime=regime,
            peak=sig.entry_price, atr=atr or 0.0)
        logger.warning(f"swing ENTER {sig.direction} {qty}x{sym} @ {sig.entry_price} "
                       f"[{strat} {regime}] stop={sig.stop_loss} target={sig.target}")
        if self.db is not None:
            self.db.record_signal(source=self.mode, symbol=sym, direction=sig.direction,
                                  taken=True, strategy=strat)
        # TODO(live): place the CNC entry + a static stop GTT here (Kite has no native
        # trailing GTT); _manage_exits then modifies that GTT each day the stop ratchets.
        # Paper simulates fills/exits.

    def _close(self, pos: SwingPosition, exit_price: float, reason: str, now: datetime):
        pnl = ((exit_price - pos.entry_price) if pos.direction == "BUY"
               else (pos.entry_price - exit_price)) * pos.quantity
        logger.warning(f"swing EXIT {pos.symbol} @ {exit_price:.2f} ({reason}) "
                       f"pnl=Rs.{pnl:.0f}  held since {pos.entry_date}")
        if self.db is not None:
            self.db.record_trade(source=self.mode, strategy=pos.strategy, regime=pos.regime,
                                 symbol=pos.symbol, direction=pos.direction, quantity=pos.quantity,
                                 entry_price=pos.entry_price, exit_price=round(exit_price, 2),
                                 entry_time=pos.entry_date, exit_time=now, pnl=round(pnl, 2),
                                 exit_reason=f"swing_{reason}")
        del self.positions[pos.symbol]

    # ── state persistence (positions survive restarts / overnight) ────────────

    def load_state(self) -> None:
        if not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            self.positions = {s: SwingPosition(**p) for s, p in data.get("positions", {}).items()}
            logger.info(f"swing: restored {len(self.positions)} open position(s)")
        except Exception as exc:
            logger.error(f"swing: could not load state — {exc}")

    def save_state(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"positions": {s: asdict(p) for s, p in self.positions.items()}}, f)
            os.replace(tmp, self.state_path)
        except OSError as exc:
            logger.error(f"swing: could not save state — {exc}")

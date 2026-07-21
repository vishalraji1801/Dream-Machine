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

# The 20 OOS-validated edges (signal-level, post-2026-01-17 holdout): donchian (manual) +
# 19 maker/gauntlet strategies. The old manual set (bb/vcb/double_reversal/…) is retired —
# vcb and double_reversal LOST money out-of-sample; bb and the rest were inconclusive.
SWING_STRATEGIES = (
    "donchian_trend_tsl",
    "maker_eadcde15", "maker_deb70ada", "maker_19d44d4e", "maker_d4cf5eb9",
    "maker_21198195", "maker_4679245d", "maker_5b132840", "maker_822bbda5",
    "maker_ebf605d5", "maker_9227a6ff",
    "mkg_2e09c633", "mkg_ff0fa479", "mkg_847ba1fe", "mkg_ba802757", "mkg_b9d2738e",
    "mkg_7fca1c98", "mkg_9e41b56c", "mkg_06e96562", "mkg_73b2fda7",
)


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
    gtt_id: Optional[int] = None   # Kite GTT OCO id (live) — modified as the trail ratchets


class SwingEngine:
    def __init__(self, cfg: dict, mode: str, db, fetch_daily: Callable,
                 index_symbol: str = "NIFTY 50",
                 state_path: str = os.path.join("logs", "swing_state.json"),
                 strategies_dir: str = "strategies",
                 fetch_holdings: Optional[Callable] = None,
                 executor=None):
        self.cfg = cfg
        self.mode = mode
        self.db = db
        self.fetch_daily = fetch_daily
        # LIVE order placement (CNC entry + GTT OCO stop/target). None in paper (simulated)
        # and until the executor is wired — live entries are skipped rather than faked.
        self.executor = executor
        # LIVE reconciliation: returns the broker's delivery holdings
        # [{tradingsymbol, quantity, average_price}, ...]. Kite is the source of truth; a GTT
        # that fired overnight / a manual sell / a partial fill all leave local state stale.
        self.fetch_holdings = fetch_holdings
        self.index_symbol = index_symbol
        self.state_path = state_path

        s = cfg.get("swing", {})
        self.capital = s.get("capital", 500_000)
        self.risk_pct = s.get("risk_pct", 1.0)
        self.max_positions = s.get("max_positions", 5)
        self.atr_mult = s.get("atr_stop_mult", 6.0)
        self.lookback_days = s.get("lookback_days", 320)
        self.max_position_pct = s.get("max_position_pct", 20.0)
        # Capital-aware sizing: deploy FREE capital per position up to max_position_value;
        # refuse (and log) a signal when free capital can't fund a >= min_position_value
        # position (below which delivery costs eat the edge). At small capital this means
        # "hold what you have, note every signal you couldn't fund" rather than dust trades.
        self.max_position_value = s.get("max_position_value", 120_000)
        self.min_position_value = s.get("min_position_value", 3_000)

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
        if self.mode == "live":            # Kite is the truth — sync BEFORE managing/entering
            self.reconcile_with_broker(now)
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

    # ── broker reconciliation (LIVE: Kite is the source of truth) ─────────────

    def reconcile_with_broker(self, now: Optional[datetime] = None) -> dict:
        """Sync local swing positions against the broker's ACTUAL delivery holdings before
        the day's logic runs. Kite is authoritative — a GTT stop that fired overnight, a
        manual sell, a partial/failed fill, or a missed cycle all leave `swing_state.json`
        stale, and acting on stale state (managing a phantom position, stopping shares you no
        longer hold) is how live bots lose money. Positions the broker no longer holds are
        recorded CLOSED; quantities are synced down to the broker's; holdings the bot never
        opened are left untouched (surfaced in the log, not managed)."""
        now = now or datetime.now()
        if self.fetch_holdings is None:
            logger.error("swing: LIVE run with NO fetch_holdings — trading on UNRECONCILED "
                         "local state (unsafe). Wire a broker-holdings source.")
            return {"reconciled": False, "reason": "no_holdings_source"}
        try:
            holdings = self.fetch_holdings() or []
        except Exception as exc:
            logger.error(f"swing: broker holdings fetch FAILED ({exc}) — refusing to trade on "
                         f"stale state this cycle")
            return {"reconciled": False, "reason": "fetch_failed"}

        held: dict = {}
        for h in holdings:
            sym = h.get("tradingsymbol") or h.get("symbol")
            held[sym] = held.get(sym, 0) + int(h.get("quantity", 0))

        closed = adjusted = 0
        for sym in list(self.positions):
            pos = self.positions[sym]
            bqty = held.get(sym, 0)
            if bqty <= 0:                       # broker no longer holds it -> exited away
                if self.executor is not None and pos.gtt_id is not None:
                    self.executor.cancel_gtt(pos.gtt_id)   # drop any orphaned GTT (no-op if fired)
                # best-effort exit price = the stop (a GTT stop is the most likely trigger);
                # tagged 'reconciled' so the P&L is understood as inferred, not a live fill.
                self._close(pos, pos.stop, "reconciled_broker_exit", now)
                closed += 1
            elif bqty < pos.quantity:           # partial exit -> sync qty down to the broker
                logger.warning(f"swing RECONCILE {sym}: broker qty {bqty} < local "
                               f"{pos.quantity} — adjusting to broker")
                pos.quantity = bqty
                adjusted += 1
            # bqty >= pos.quantity: the bot's position is intact (extra is a manual add we
            # deliberately do NOT manage) — leave it.

        untracked = [s for s, q in held.items() if q > 0 and s not in self.positions]
        if untracked:
            logger.warning(f"swing RECONCILE: broker holds untracked names {untracked} "
                           f"(not opened by the bot — ignored, not managed)")
        self.save_state()
        logger.warning(f"swing RECONCILE: closed={closed} adjusted={adjusted} "
                       f"open={len(self.positions)} untracked={len(untracked)}")
        return {"reconciled": True, "closed": closed, "adjusted": adjusted,
                "open": len(self.positions), "untracked": len(untracked)}

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

            # ATR-trailing strategies: donchian + all maker/gauntlet edges (their backtested
            # exit IS the ATR trail, so they only replicate WITH this ratchet). Mean-reverters
            # (bb, double_reversal) keep their fixed target/stop and are untouched here.
            if (pos.strategy == "donchian_trend_tsl"
                    or pos.strategy.startswith(("maker_", "mkg_"))):
                prev_stop = pos.stop
                if pos.direction == "BUY":
                    pos.peak = max(pos.peak, close)
                    pos.stop = max(pos.stop, pos.peak - self.atr_mult * atr)
                else:
                    pos.peak = min(pos.peak, close)
                    pos.stop = min(pos.stop, pos.peak + self.atr_mult * atr)
                # Kite has no native trailing GTT — when the stop ratchets, the bot MODIFIES
                # the exchange GTT itself so the (raised) stop is enforced even while offline.
                if (self.mode == "live" and pos.stop != prev_stop
                        and self.executor is not None and pos.gtt_id is not None):
                    self.executor.modify_gtt_oco(pos.gtt_id, pos.symbol, pos.direction,
                                                 pos.quantity, round(pos.stop, 2),
                                                 round(pos.target, 2), close)

            # LIVE: the exchange-side GTT OCO owns the actual exit (it fires anytime, even
            # when the bot is offline); it is detected next morning by reconcile_with_broker.
            # So we do NOT simulate an exit here — that would double-count / diverge from the
            # real fill. PAPER: simulate the exit against the daily bar and book it.
            if self.mode == "live":
                continue
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
        # NOTE: we do NOT early-return when positions are full — we still scan so that every
        # real signal we can't fund is NOTED (refused with a reason), turning the capital
        # limit into missed-opportunity data instead of a silent skip.
        if not active:
            return 0
        entered = 0
        for sym in self.cfg["trading"]["watchlist"]:
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
                if abs(sig.entry_price - sig.stop_loss) <= 0 or sig.entry_price <= 0:
                    continue
                # A real signal fired. Deploy FREE capital up to max_position_value; a signal
                # that can't get a >= min_position_value position is REFUSED and logged.
                deployed = sum(p.entry_price * p.quantity for p in self.positions.values())
                free = self.capital - deployed
                qty = int(min(free, self.max_position_value) / sig.entry_price)
                pos_value = qty * sig.entry_price
                if len(self.positions) >= self.max_positions:
                    self._refuse(sym, a.name, sig, "slot_full", free, now)
                elif qty <= 0 or pos_value < self.min_position_value:
                    self._refuse(sym, a.name, sig, "insufficient_capital", free, now)
                elif self._open(sym, a.name, sig, qty, regime.regime.value, _atr(df, 14), now):
                    entered += 1                 # live entry may fail to fill -> not opened
                break            # this symbol's signal is handled (taken or noted)
        return entered

    def _refuse(self, sym, strat, sig, reason: str, free: float, now: datetime) -> None:
        """A real signal fired but capital couldn't fund a viable position — do NOT trade;
        maintain existing positions and NOTE the refused trigger (the missed-opportunity
        record at small capital)."""
        logger.warning(f"swing REFUSED {sig.direction} {sym} [{strat}] reason={reason} "
                       f"free=Rs.{free:.0f} entry={sig.entry_price} "
                       f"stop={sig.stop_loss} target={sig.target}")
        if self.db is not None:
            try:
                self.db.record_signal(source=self.mode, symbol=sym, direction=sig.direction,
                                      taken=False, reason=reason, strategy=strat)
            except Exception as exc:
                logger.error(f"swing: refusal record failed — {exc}")

    def _open(self, sym, strat, sig, qty, regime, atr, now) -> bool:
        """Open a position. LIVE: place the CNC entry, confirm the fill, then place a GTT OCO
        (stop + target) safety net at the exchange — records the ACTUAL fill price/qty. If the
        entry doesn't fill, nothing is opened (returns False). Paper: simulated at the signal
        price. Returns True iff a position was opened."""
        entry_price, gtt_id = sig.entry_price, None
        if self.mode == "live":
            if self.executor is None:
                logger.error(f"swing LIVE: no executor wired — cannot place {sym} entry")
                return False
            oid = self.executor.place_order(sym, sig.direction, qty, sig.entry_price,
                                            order_type="MARKET")
            status = self.executor.monitor_order(oid) if oid else None
            if (not status or status.get("status") != "COMPLETE"
                    or int(status.get("filled_quantity", 0)) <= 0):
                logger.error(f"swing LIVE entry not filled for {sym} — not opening")
                return False
            entry_price = float(status.get("average_price") or sig.entry_price)
            qty = int(status.get("filled_quantity") or qty)
            # exchange-side safety net: SL + target OCO (survives the bot being offline)
            gtt_id = self.executor.place_gtt_oco(sym, sig.direction, qty, sig.stop_loss,
                                                 sig.target, entry_price)
        self.positions[sym] = SwingPosition(
            symbol=sym, strategy=strat, direction=sig.direction,
            entry_price=entry_price, quantity=qty, stop=sig.stop_loss,
            target=sig.target, entry_date=now.date().isoformat(), regime=regime,
            peak=entry_price, atr=atr or 0.0, gtt_id=gtt_id)
        logger.warning(f"swing ENTER {sig.direction} {qty}x{sym} @ {entry_price} "
                       f"[{strat} {regime}] stop={sig.stop_loss} target={sig.target} gtt={gtt_id}")
        if self.db is not None:
            self.db.record_signal(source=self.mode, symbol=sym, direction=sig.direction,
                                  taken=True, strategy=strat)
        return True

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

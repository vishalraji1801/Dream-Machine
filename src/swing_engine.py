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

from src.costs import estimate_costs, trade_leg_values
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
        # Shadow book: a parallel ledger that takes EVERY signal (incl. the ones the real book
        # refuses for slot/capital), sized at the SAME per-position capital as paper
        # (max_position_value), and tracks its hypothetical P&L — so you learn, at your real
        # scale, whether the trades you couldn't fund would have won or lost. Purely analytical
        # (never places an order); recorded to the ledger as source='shadow'.
        self.shadow_enabled = s.get("shadow_enabled", True)
        self.shadow: dict = {}
        # Regime exposure throttle: {regime: multiplier} on NEW entries per cycle. The regime
        # signal's only real lever over regime-agnostic edges (it can't pick among them). A
        # missing regime defaults to 1.0 (full appetite); it can only ever reduce entries.
        self.regime_exposure = s.get("regime_exposure", {})

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
        self._refused = 0                  # signals that fired but couldn't be funded/slotted
        if self.mode == "live":            # Kite is the truth — sync BEFORE managing/entering
            self.reconcile_with_broker(now)
        idx = self.fetch_daily(self.index_symbol, self.lookback_days)
        if idx is None or len(idx) < 60:
            logger.warning("swing: insufficient index daily data — skipping run")
            return {"regime": "UNKNOWN", "entered": 0, "exited": 0, "refused": 0,
                    "open": len(self.positions)}

        state = compute_market_state(idx, self.ms_cfg)
        self._prev_regime = classify(state, self._prev_regime, self.regime_cfg)
        regime = self._prev_regime

        exited = self._manage_exits(now)
        active = route(regime, self.metas, self.premarket, self.router_cfg)
        entered = self._scan_entries(regime, active, now)
        if self.shadow_enabled:                 # unconstrained parallel book (analytical)
            self._manage_shadow(now)
            self._scan_shadow(regime, active, now)
        self.save_state()

        if self.db is not None:
            try:
                self.db.record_routing(source=self.mode, regime=regime.regime.value,
                                       confidence=regime.confidence,
                                       active=routing_records(active),
                                       config_version="swing")
            except Exception as exc:
                logger.error(f"swing: routing persist failed — {exc}")

        # The winners are regime-AGNOSTIC (validated ON in every regime), so the router runs
        # in pass-through: all edges active every regime. The regime signal's only real lever
        # is the exposure throttle below — log it explicitly so the router's role is honest.
        mult = self.regime_exposure.get(regime.regime.value, 1.0)
        logger.warning(f"swing: regime={regime.regime.value} conf={regime.confidence:.2f} "
                       f"router=pass-through({len(active)} edges) exposure_x{mult:g} "
                       f"exited={exited} entered={entered} open={len(self.positions)}")
        return {"regime": regime.regime.value, "entered": entered, "exited": exited,
                "refused": self._refused, "open": len(self.positions)}

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
            exit_price, reason = self._simulate_exit(pos, bar)
            if exit_price is not None:
                self._close(pos, exit_price, reason, now)
                exited += 1
        return exited

    def _simulate_exit(self, pos: SwingPosition, bar) -> tuple:
        """PAPER exit fill on the daily bar, modelling gap-through-stop + slippage.
        A stop the bar GAPPED past fills at the (worse) OPEN, not the stop price — a
        real GTT/market stop can't fill at a level the market leapt over, so booking
        the exit at the stop flatters paper P&L and hides tail risk. A configurable
        slippage further worsens stop fills. Targets fill at the better of open/target
        (a gap through the target is a fill at the open). Returns (price, reason)."""
        o, high, low = float(bar["open"]), float(bar["high"]), float(bar["low"])
        slip = self.cfg.get("paper_trading", {}).get("simulated_slippage_pct", 0.0) / 100.0
        if pos.direction == "BUY":
            if low <= pos.stop:
                px = min(o, pos.stop)                 # gap-down opens below the stop -> fill there
                return round(px * (1 - slip), 2), "stop"
            if pos.target and high >= pos.target:
                px = max(o, pos.target)               # gap-up opens above the target
                return round(px, 2), "target"
        else:
            if high >= pos.stop:
                px = max(o, pos.stop)
                return round(px * (1 + slip), 2), "stop"
            if pos.target and low <= pos.target:
                px = min(o, pos.target)
                return round(px, 2), "target"
        return None, None

    # ── entries ───────────────────────────────────────────────────────────────

    def _scan_entries(self, regime, active: list, now: datetime) -> int:
        # Collect EVERY firing signal (one per symbol), then fill the scarce slot(s) with the
        # HIGHEST-CONVICTION ones first — an always-on strategy (e.g. pdh+limit that fires on
        # nearly every name) must not monopolise the single Rs.5000 slot. Everything we can't
        # fund is still NOTED (refused) as missed-opportunity data.
        if not active:
            return 0
        fires = []                       # (sym, name, sig, weight, atr)
        for sym in self.cfg["trading"]["watchlist"]:
            if sym in self.positions:
                continue
            df = self.fetch_daily(sym, self.lookback_days)
            if df is None or len(df) < 210:
                continue
            for a in active:
                scfg = {**self.cfg["strategy"], **a.param_set.params, "name": a.name}
                sig = generate_signal(sym, df, scfg)
                if sig.direction == "HOLD" or sig.entry_price <= 0 \
                        or abs(sig.entry_price - sig.stop_loss) <= 0:
                    continue
                fires.append((sym, a.name, sig, a.weight, _atr(df, 14)))
                break                    # one signal per symbol
        if not fires:
            return 0
        # CONVICTION rank: a strategy that fired on FEWER names is more selective (higher
        # conviction) — prefer it, then higher router weight, so the slot diversifies across
        # setups over time instead of always going to the flooder's first watchlist name.
        from collections import Counter
        freq = Counter(name for _, name, _, _, _ in fires)
        fires.sort(key=lambda f: (freq[f[1]], -f[3]))
        # Regime exposure throttle: cap NEW entries THIS cycle by the regime's risk appetite.
        mult = self.regime_exposure.get(regime.regime.value, 1.0)
        slots_free = max(0, self.max_positions - len(self.positions))
        budget = slots_free if mult >= 1.0 else int(slots_free * mult)
        entered = 0
        for sym, name, sig, _w, atr in fires:
            deployed = sum(p.entry_price * p.quantity for p in self.positions.values())
            free = self.capital - deployed
            qty = int(min(free, self.max_position_value) / sig.entry_price)
            pos_value = qty * sig.entry_price
            if len(self.positions) >= self.max_positions:
                self._refuse(sym, name, sig, "slot_full", free, now)
            elif entered >= budget:
                self._refuse(sym, name, sig, "regime_throttle", free, now)
            elif qty <= 0 or pos_value < self.min_position_value:
                self._refuse(sym, name, sig, "insufficient_capital", free, now)
            elif self._open(sym, name, sig, qty, regime.regime.value, atr, now):
                entered += 1             # (best-ranked fill first; rest get refused for capital)
        return entered

    def _refuse(self, sym, strat, sig, reason: str, free: float, now: datetime) -> None:
        """A real signal fired but capital couldn't fund a viable position — do NOT trade;
        maintain existing positions and NOTE the refused trigger (the missed-opportunity
        record at small capital)."""
        self._refused = getattr(self, "_refused", 0) + 1
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

    def _net_pnl(self, pos: SwingPosition, exit_price: float) -> tuple[float, float, float]:
        """(gross, cost, net) for a round trip — costs are the Zerodha CNC delivery
        charges (STT both legs, exchange/SEBI, stamp, flat DP charge, GST) from the
        `costs:` config. The flat DP charge dominates at small size, so net P&L is
        what actually matters — every recorded swing/shadow trade books NET."""
        gross = ((exit_price - pos.entry_price) if pos.direction == "BUY"
                 else (pos.entry_price - exit_price)) * pos.quantity
        buy_v, sell_v = trade_leg_values(pos.direction, pos.entry_price, exit_price, pos.quantity)
        cost = estimate_costs(buy_v, sell_v, self.cfg)
        return gross, cost, gross - cost

    def _close(self, pos: SwingPosition, exit_price: float, reason: str, now: datetime):
        gross, cost, pnl = self._net_pnl(pos, exit_price)
        logger.warning(f"swing EXIT {pos.symbol} @ {exit_price:.2f} ({reason}) "
                       f"net=Rs.{pnl:.0f} (gross Rs.{gross:.0f} - cost Rs.{cost:.0f})  "
                       f"held since {pos.entry_date}")
        if self.db is not None:
            self.db.record_trade(source=self.mode, strategy=pos.strategy, regime=pos.regime,
                                 symbol=pos.symbol, direction=pos.direction, quantity=pos.quantity,
                                 entry_price=pos.entry_price, exit_price=round(exit_price, 2),
                                 entry_time=pos.entry_date, exit_time=now, pnl=round(pnl, 2),
                                 exit_reason=f"swing_{reason}")
        del self.positions[pos.symbol]

    # ── shadow book (unconstrained parallel ledger — the "what if" P&L) ────────

    def _scan_shadow(self, regime, active: list, now: datetime) -> None:
        """Realistic-portfolio counterfactual: the SAME account (capital, per-name cap,
        one position per symbol, NET costs) but WITHOUT the max_positions slot limit the
        real book obeys. So the shadow equity curve is actually achievable at real capital
        — and, by holding every symbol the slot cap turned away, it measures exactly what
        that position-count cap costs (or saves). Keyed sym|strat (first strategy to fire
        wins the symbol). Not an unbounded per-signal ledger — that implied capital that
        doesn't exist."""
        held = {k.split("|")[0] for k in self.shadow}          # symbols already in the shadow book
        deployed = sum(p.entry_price * p.quantity for p in self.shadow.values())
        for sym in self.cfg["trading"]["watchlist"]:
            if sym in held:
                continue                        # one shadow position per symbol (realistic)
            if deployed >= self.capital:
                break                           # account fully deployed — cannot fund more
            df = self.fetch_daily(sym, self.lookback_days)
            if df is None or len(df) < 210:
                continue
            for a in active:                    # first firing strategy wins the symbol
                scfg = {**self.cfg["strategy"], **a.param_set.params, "name": a.name}
                sig = generate_signal(sym, df, scfg)
                if (sig.direction == "HOLD" or sig.entry_price <= 0
                        or abs(sig.entry_price - sig.stop_loss) <= 0):
                    continue
                free = self.capital - deployed
                qty = int(min(free, self.max_position_value) / sig.entry_price)
                if qty < 1:
                    break                       # can't fund one share here -> skip the symbol
                self.shadow[f"{sym}|{a.name}"] = SwingPosition(
                    symbol=sym, strategy=a.name, direction=sig.direction,
                    entry_price=sig.entry_price, quantity=qty, stop=sig.stop_loss,
                    target=sig.target, entry_date=now.date().isoformat(),
                    regime=regime.regime.value, peak=sig.entry_price, atr=_atr(df, 14) or 0.0)
                deployed += sig.entry_price * qty
                break

    def _manage_shadow(self, now: datetime) -> None:
        """Trail/exit the shadow book on the daily bar and book realized shadow P&L to the
        ledger as source='shadow' (never touches the broker — purely a counterfactual)."""
        for key in list(self.shadow):
            pos = self.shadow[key]
            df = self.fetch_daily(pos.symbol, self.lookback_days)
            if df is None or df.empty:
                continue
            bar = df.iloc[-1]
            high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])
            atr = _atr(df, 14) or pos.atr
            if (pos.strategy == "donchian_trend_tsl"
                    or pos.strategy.startswith(("maker_", "mkg_"))):     # ATR trail
                if pos.direction == "BUY":
                    pos.peak = max(pos.peak, close)
                    pos.stop = max(pos.stop, pos.peak - self.atr_mult * atr)
                else:
                    pos.peak = min(pos.peak, close)
                    pos.stop = min(pos.stop, pos.peak + self.atr_mult * atr)
            exit_price, reason = self._simulate_exit(pos, bar)
            if exit_price is not None:
                _g, _c, pnl = self._net_pnl(pos, exit_price)      # book NET (same cost model)
                if self.db is not None:
                    self.db.record_trade(source="shadow", strategy=pos.strategy, regime=pos.regime,
                                         symbol=pos.symbol, direction=pos.direction,
                                         quantity=pos.quantity, entry_price=pos.entry_price,
                                         exit_price=round(exit_price, 2), entry_time=pos.entry_date,
                                         exit_time=now, pnl=round(pnl, 2),
                                         exit_reason=f"shadow_{reason}")
                del self.shadow[key]

    # ── state persistence (positions survive restarts / overnight) ────────────

    def load_state(self) -> None:
        if not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            self.positions = {s: SwingPosition(**p) for s, p in data.get("positions", {}).items()}
            self.shadow = {k: SwingPosition(**p) for k, p in data.get("shadow", {}).items()}
            logger.info(f"swing: restored {len(self.positions)} open position(s), "
                        f"{len(self.shadow)} shadow")
        except Exception as exc:
            logger.error(f"swing: could not load state — {exc}")

    def save_state(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"positions": {s: asdict(p) for s, p in self.positions.items()},
                           "shadow": {k: asdict(p) for k, p in self.shadow.items()}}, f)
            os.replace(tmp, self.state_path)
        except OSError as exc:
            logger.error(f"swing: could not save state — {exc}")

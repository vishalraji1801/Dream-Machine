"""
Live router integration (regime router → the intraday loop).

Wraps the pure regime/router stack for use inside main.py's 5-min cycle:
  - carries the RegimeState across cycles (hysteresis is stateful),
  - each cycle: MarketState(index) → classify → route → active strategies,
  - builds the per-strategy config (base strategy cfg + the regime's param set),
  - persists the routing decision to the ledger,
  - sizes each entry by the strategy's weight.

Only INTRADAY strategies fire on 5-min bars; daily strategies (bb/donchian) are
positional and simply return HOLD here — that's expected. The router trades
nothing when no strategy has a positive learned fit in the current regime.
"""
from datetime import datetime
from typing import Optional

from src.logger import get_logger
from src.market_state import compute_market_state
from src.regime import RegimeConfig, RegimeState, classify
from src.router import (PremarketAllocation, RouterConfig, route, routing_records)
from src.strategy import generate_signal
from src.strategy_meta import load_strategy_dir
from src.swing_engine import SWING_STRATEGIES   # daily strategies belong to the swing sleeve

logger = get_logger("live_router")


class LiveRouter:
    def __init__(self, cfg: dict, mode: str = "paper", db=None,
                 strategies_dir: str = "strategies"):
        self.cfg = cfg
        self.mode = mode
        self.db = db
        # INTRADAY strategies only — daily/swing strategies run in the swing sleeve
        self.metas = [m for n, m in load_strategy_dir(strategies_dir).items()
                      if n not in SWING_STRATEGIES]
        self.regime_cfg = RegimeConfig(**{k: v for k, v in cfg.get("regime", {}).items()
                                          if k in RegimeConfig.__dataclass_fields__})
        self.ms_cfg = cfg.get("market_state", {})
        r = cfg.get("router", {})
        self.router_cfg = RouterConfig(
            mode=mode, min_fit_pf=r.get("min_fit_pf", 1.0),
            min_trades=r.get("min_trades", 30),
            max_weight_change=r.get("max_weight_change", 0.2))
        self.premarket = PremarketAllocation(ceiling=r.get("ceiling", 1.0))
        # how often to re-check the regime (minutes). 0 = every cycle.
        self.regime_interval = r.get("regime_interval_minutes", 0) * 60
        self._last_regime_time: Optional[datetime] = None
        self._prev_regime: Optional[RegimeState] = None
        self._prev_weights: dict = {}
        self._active: list = []
        self.regime: Optional[RegimeState] = None

    def _due_for_regime(self, now: datetime) -> bool:
        if self.regime is None or self.regime_interval <= 0 or self._last_regime_time is None:
            return True
        return (now - self._last_regime_time).total_seconds() >= self.regime_interval

    def step(self, index_df, now: Optional[datetime] = None) -> list:
        """Advance one cycle. The regime is only re-checked every
        `regime_interval_minutes` (default: every cycle); between checks the last
        regime + active strategies are reused, so entries are still scanned each
        cycle. Returns the active strategies (possibly empty = trade nothing)."""
        now = now or datetime.now()
        if not self._due_for_regime(now):
            return self._active                       # reuse cached regime this cycle

        if index_df is None or len(index_df) == 0:
            logger.warning("router: no index data — trading nothing this cycle")
            self._active = []
            return []
        state = compute_market_state(index_df, self.ms_cfg)
        self._prev_regime = classify(state, self._prev_regime, self.regime_cfg)
        self.regime = self._prev_regime
        self._last_regime_time = now

        active = route(self.regime, self.metas, self.premarket, self.router_cfg,
                       self._prev_weights)
        self._prev_weights = {a.name: a.weight for a in active}
        self._active = active

        if self.db is not None:
            try:
                self.db.record_routing(
                    source=self.mode, regime=self.regime.regime.value,
                    confidence=self.regime.confidence, active=routing_records(active),
                    config_version=self.regime.config_version)
            except Exception as exc:
                logger.error(f"router: failed to persist routing — {exc}")

        names = [f"{a.name}:{a.weight:.2f}" for a in active]
        logger.info(f"router: regime={self.regime.regime.value} "
                    f"conf={self.regime.confidence:.2f} active=[{', '.join(names) or 'NONE'}]")
        return active

    @property
    def active(self) -> list:
        return self._active

    def signals_for(self, symbol: str, df) -> list:
        """Signals from every active strategy on `symbol` (non-HOLD only).
        Returns [(signal, active_strategy)], highest weight first."""
        out = []
        for a in sorted(self._active, key=lambda x: x.weight, reverse=True):
            scfg = {**self.cfg["strategy"], **a.param_set.params, "name": a.name}
            sig = generate_signal(symbol, df, scfg)
            if sig.direction != "HOLD":
                out.append((sig, a))
        return out

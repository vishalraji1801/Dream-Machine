"""
MTF veto counterfactual replay (SCRUM-108 / B2).

Counting vetoes is not evidence. For every signal the MTF gate vetoed, this
replays what WOULD have happened — hit stop-loss or target first — from the
candles that followed, and aggregates the answer into the only number that
decides adoption: did vetoes avoid more loss than they forfeited in wins?

Pure functions (candles in, verdict out). The nightly wiring that reads
trades.db vetoes + stored candles is a thin wrapper over `replay_outcome`.
"""


import pandas as pd


def replay_outcome(direction: str, entry: float, stop_loss: float, target: float,
                   future_df: pd.DataFrame) -> dict:
    """
    Walk `future_df` (candles AFTER the signal, oldest first) and decide whether
    a BUY/SELL from `entry` would have hit stop_loss or target first.
    SL is assumed to hit first if both fall inside one candle (conservative).
    Returns {outcome: 'target'|'sl'|'none', pnl_per_share}.
    """
    if future_df is None or future_df.empty:
        return {"outcome": "none", "pnl_per_share": 0.0}
    for _, c in future_df.iterrows():
        high, low = float(c["high"]), float(c["low"])
        if direction == "BUY":
            if low <= stop_loss:
                return {"outcome": "sl", "pnl_per_share": round(stop_loss - entry, 2)}
            if high >= target:
                return {"outcome": "target", "pnl_per_share": round(target - entry, 2)}
        else:  # SELL
            if high >= stop_loss:
                return {"outcome": "sl", "pnl_per_share": round(entry - stop_loss, 2)}
            if low <= target:
                return {"outcome": "target", "pnl_per_share": round(entry - target, 2)}
    return {"outcome": "none", "pnl_per_share": 0.0}


def aggregate_vetoes(replays: list[dict]) -> dict:
    """
    replays: list of replay_outcome dicts. Returns the adoption verdict:
    a veto that would have LOST is an avoided loss (good); one that would have
    WON is a forfeited win (bad). net_benefit > 0 means the gate helped.
    """
    avoided_loss = sum(-r["pnl_per_share"] for r in replays if r["pnl_per_share"] < 0)
    forfeited_win = sum(r["pnl_per_share"] for r in replays if r["pnl_per_share"] > 0)
    return {
        "vetoes": len(replays),
        "would_have_lost": sum(1 for r in replays if r["outcome"] == "sl"),
        "would_have_won": sum(1 for r in replays if r["outcome"] == "target"),
        "avoided_loss": round(avoided_loss, 2),
        "forfeited_win": round(forfeited_win, 2),
        "net_benefit": round(avoided_loss - forfeited_win, 2),
    }


def format_report(agg: dict) -> str:
    verdict = "HELPED" if agg["net_benefit"] > 0 else "HURT"
    return (
        f"MTF veto counterfactual: {agg['vetoes']} vetoes | "
        f"{agg['would_have_lost']} would-lose, {agg['would_have_won']} would-win | "
        f"avoided Rs.{agg['avoided_loss']} loss, forfeited Rs.{agg['forfeited_win']} win | "
        f"net Rs.{agg['net_benefit']} -> gate {verdict}")

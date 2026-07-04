from src.go_live import evaluate_readiness, format_report


def _trades(n, pnl_each, day_offset=0):
    out = []
    for i in range(n):
        day = 4 + (i % 6)  # spread across up to 6 days
        out.append({"pnl": pnl_each,
                    "entry_time": f"2026-07-{day + day_offset:02d} 10:00:00"})
    return out


def test_ready_when_all_criteria_met():
    trades = _trades(24, 100.0)  # 24 trades, all winners, 6 days
    report = evaluate_readiness(trades)
    assert report["ready"] is True
    assert all(passed for passed, *_ in report["checks"].values())


def test_not_ready_on_negative_pnl():
    winners = _trades(15, 100.0)
    losers = [{"pnl": -300.0, "entry_time": f"2026-07-0{d} 11:00:00"} for d in range(1, 8)]
    report = evaluate_readiness(winners + losers)
    assert report["ready"] is False
    assert report["checks"]["net_pnl"][0] is False


def test_not_ready_on_too_few_trades():
    report = evaluate_readiness(_trades(5, 100.0))
    assert report["ready"] is False
    assert report["checks"]["trade_count"][0] is False


def test_not_ready_on_too_few_days():
    trades = [{"pnl": 100.0, "entry_time": "2026-07-06 10:00:00"} for _ in range(30)]
    report = evaluate_readiness(trades)
    assert report["checks"]["trading_days"][0] is False


def test_custom_criteria_override():
    trades = _trades(3, 50.0)
    report = evaluate_readiness(trades, {"min_trades": 2, "min_trading_days": 1,
                                         "min_profit_factor": 1.0, "min_win_rate": 40.0})
    assert report["ready"] is True


def test_profit_factor_computed():
    trades = [{"pnl": 200.0, "entry_time": "2026-07-06 10:00"},
              {"pnl": -100.0, "entry_time": "2026-07-07 10:00"}]
    report = evaluate_readiness(trades)
    assert report["summary"]["profit_factor"] == 2.0


def test_empty_trades_not_ready():
    report = evaluate_readiness([])
    assert report["ready"] is False


def test_format_report_contains_verdict():
    report = evaluate_readiness(_trades(24, 100.0))
    text = format_report(report)
    assert "READY" in text
    assert "never flips" in text

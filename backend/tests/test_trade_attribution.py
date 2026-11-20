from app.execution.trade_attribution import build_trade_attribution
from app.broker.bridge import MT5ExecutionDeal


def deal(ticket, entry, side, volume, *, profit=0.0, commission=0.0, swap=0.0, fee=0.0,
         position="9001", at=None, magic=61119001, symbol="EURUSDM"):
    return {
        "deal_ticket": str(ticket), "order_ticket": "o" + str(ticket),
        "position_id": position, "terminal_id": "terminal-demo", "environment": "demo",
        "server": "Exness-MT5Trial", "symbol": symbol, "side": side, "entry": entry,
        "volume_lots": volume, "price": 1.1, "magic": magic, "comment": "",
        "occurred_at": at or f"2026-11-19T10:0{ticket}:00+00:00",
        "profit": profit, "commission": commission, "swap": swap, "fee": fee,
    }


def test_partial_entries_and_exits_are_one_closed_trade_with_all_cash_components():
    rows = [
        deal(1, "in", "buy", 0.02, commission=-0.10),
        deal(2, "in", "buy", 0.01, commission=-0.05),
        deal(3, "out", "sell", 0.01, profit=2.0, commission=-0.05),
        deal(4, "out", "sell", 0.02, profit=4.0, commission=-0.10, swap=-0.20, fee=-0.03),
    ]
    result = build_trade_attribution(rows)
    assert result["closed_trade_count"] == 1
    assert result["pnl_complete_trade_count"] == 1
    assert result["net_realized_pnl"] == 5.47
    assert result["win_rate_pct"] == 100.0
    assert result["open_position_count"] == 0


def test_partial_exit_does_not_finalize_remaining_position():
    rows = [
        deal(1, "in", "buy", 0.03),
        deal(2, "out", "sell", 0.01, profit=1.0),
    ]
    result = build_trade_attribution(rows)
    assert result["closed_trade_count"] == 0
    assert result["open_position_count"] == 1
    assert result["open_positions"][0]["remaining_volume_lots"] == 0.02
    assert result["net_realized_pnl"] == 0


def test_inout_reversal_closes_old_cycle_and_starts_new_cycle():
    rows = [
        deal(1, "in", "buy", 0.02, commission=-0.10),
        deal(2, "inout", "sell", 0.03, profit=3.0, commission=-0.15),
        deal(3, "out", "buy", 0.01, profit=-0.5, commission=-0.05),
    ]
    result = build_trade_attribution(rows)
    assert result["closed_trade_count"] == 2
    assert result["pnl_complete_trade_count"] == 2
    assert result["open_position_count"] == 0
    assert result["net_realized_pnl"] == 2.2


def test_legacy_missing_cash_fields_are_not_fabricated_as_zero():
    rows = [
        deal(1, "in", "buy", 0.01),
        {**deal(2, "out", "sell", 0.01, profit=1.0), "commission": None},
    ]
    result = build_trade_attribution(rows)
    assert result["closed_trade_count"] == 1
    assert result["pnl_complete_trade_count"] == 0
    assert result["pnl_incomplete_trade_count"] == 1
    assert result["net_realized_pnl"] == 0
    assert result["expectancy_per_trade"] is None


def test_unmatched_exit_is_reported_not_counted_as_a_trade():
    result = build_trade_attribution([deal(1, "out", "sell", 0.01, profit=5.0)])
    assert result["closed_trade_count"] == 0
    assert result["unmatched_deal_count"] == 1


def test_deal_model_rejects_non_finite_broker_cash_amount():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        MT5ExecutionDeal(
            deal_ticket="1", order_ticket="2", position_id="3", symbol="EURUSDM",
            side="buy", entry="in", volume_lots=0.01, price=1.1, magic=1,
            occurred_at="2026-11-19T10:00:00+00:00", profit=float("nan"),
        )

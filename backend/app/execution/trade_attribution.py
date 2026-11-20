"""Conservative round-trip reconstruction from broker deal history."""
from __future__ import annotations

from typing import Any

CASH_FIELDS = ("profit", "commission", "swap", "fee")
EPSILON = 1e-8


def _cash(deal: dict[str, Any]) -> tuple[dict[str, float], bool]:
    complete = all(deal.get(key) is not None for key in CASH_FIELDS)
    return ({key: float(deal[key] or 0.0) for key in CASH_FIELDS}, complete)


def _add_cash(target: dict[str, float], source: dict[str, float], factor: float = 1.0) -> None:
    for key in CASH_FIELDS:
        target[key] += source[key] * factor


def build_trade_attribution(deals: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconstruct fully closed position cycles; expose partial/unmatched evidence separately.

    MT5 POSITION_IDENTIFIER is the lifecycle key. Partial exits remain one trade;
    INOUT closes the old exposure and starts a new cycle with any reversed volume.
    """
    positions: dict[tuple[str, str], dict[str, Any]] = {}
    closed: list[dict[str, Any]] = []
    unmatched = 0
    incomplete = 0
    missing_cash_deals = 0

    def deal_order(deal: dict[str, Any]) -> tuple[str, int, int | str]:
        ticket = str(deal.get("deal_ticket") or "")
        try:
            return (deal["occurred_at"], 0, int(ticket))
        except (TypeError, ValueError):
            return (deal["occurred_at"], 1, ticket)

    # MT5 bridge timestamps have second resolution; numeric tickets preserve
    # broker sequence when several deals share the same second.
    ordered = sorted(deals, key=deal_order)
    for deal in ordered:
        position_id = str(deal.get("position_id") or "")
        if not position_id:
            unmatched += 1
            continue
        key = (str(deal.get("terminal_id", "")), position_id)
        state = positions.get(key)
        side_sign = 1 if deal["side"] == "buy" else -1
        volume = float(deal["volume_lots"])
        cash, cash_complete = _cash(deal)
        if not cash_complete:
            missing_cash_deals += 1

        def start(direction: int, amount: float, deal_cash: dict[str, float], cash_ok: bool) -> dict[str, Any]:
            return {
                "direction": direction, "volume": amount,
                "magic": int(deal["magic"]), "symbol": deal["symbol"],
                "terminal_id": deal.get("terminal_id", ""),
                "opened_at": deal["occurred_at"], "last_at": deal["occurred_at"],
                "cash": dict(deal_cash), "cash_complete": cash_ok,
                "deal_count": 1, "position_id": position_id,
            }

        def finish(current: dict[str, Any], at: str) -> None:
            net = sum(current["cash"].values()) if current["cash_complete"] else None
            closed.append({
                "position_id": current["position_id"], "terminal_id": current["terminal_id"],
                "magic": current["magic"], "symbol": current["symbol"],
                "opened_at": current["opened_at"], "closed_at": at,
                "volume_lots": current["closed_volume"],
                "deal_count": current["deal_count"],
                "profit": current["cash"]["profit"] if current["cash_complete"] else None,
                "commission": current["cash"]["commission"] if current["cash_complete"] else None,
                "swap": current["cash"]["swap"] if current["cash_complete"] else None,
                "fee": current["cash"]["fee"] if current["cash_complete"] else None,
                "net_pnl": net, "pnl_complete": current["cash_complete"],
            })

        if deal["entry"] == "in":
            if state is None:
                state = start(side_sign, volume, cash, cash_complete)
                state["closed_volume"] = 0.0
                positions[key] = state
            elif state["direction"] == side_sign:
                state["volume"] += volume
                state["closed_volume"] += 0.0
                _add_cash(state["cash"], cash)
                state["cash_complete"] = state["cash_complete"] and cash_complete
                state["deal_count"] += 1
                state["last_at"] = deal["occurred_at"]
            else:
                unmatched += 1
            continue

        if state is None or state["direction"] == side_sign:
            unmatched += 1
            continue

        if deal["symbol"] != state["symbol"]:
            incomplete += 1
            state["cash_complete"] = False

        if deal["entry"] == "inout":
            if volume + EPSILON < state["volume"]:
                incomplete += 1
                state["cash_complete"] = False
            close_volume = min(state["volume"], volume)
            close_ratio = close_volume / volume
            # Broker profit and accumulated swap belong to the exposure being
            # closed. Deal commission/fee are split by executed volume.
            state["cash"]["profit"] += cash["profit"]
            state["cash"]["swap"] += cash["swap"]
            state["cash"]["commission"] += cash["commission"] * close_ratio
            state["cash"]["fee"] += cash["fee"] * close_ratio
            state["cash_complete"] = state["cash_complete"] and cash_complete
            state["deal_count"] += 1
            state["closed_volume"] += close_volume
            remaining_old = state["volume"] - close_volume
            if remaining_old <= EPSILON:
                finish(state, deal["occurred_at"])
                positions.pop(key, None)
            else:
                state["volume"] = remaining_old
            reverse_volume = volume - close_volume
            if reverse_volume > EPSILON:
                reverse_cash = {
                    "profit": 0.0, "swap": 0.0,
                    "commission": cash["commission"] * (1.0 - close_ratio),
                    "fee": cash["fee"] * (1.0 - close_ratio),
                }
                positions[key] = start(side_sign, reverse_volume, reverse_cash, cash_complete)
                positions[key]["closed_volume"] = 0.0
            continue

        # OUT / OUT_BY: close only the broker-reported volume; never over-close.
        if deal["entry"] not in ("out", "out_by"):
            unmatched += 1
            continue
        close_volume = min(state["volume"], volume)
        if volume > state["volume"] + EPSILON:
            incomplete += 1
            state["cash_complete"] = False
        _add_cash(state["cash"], cash)
        state["cash_complete"] = state["cash_complete"] and cash_complete
        state["deal_count"] += 1
        state["closed_volume"] += close_volume
        state["volume"] -= close_volume
        state["last_at"] = deal["occurred_at"]
        if state["volume"] <= EPSILON:
            finish(state, deal["occurred_at"])
            positions.pop(key, None)

    open_positions = [
        {"position_id": state["position_id"], "symbol": state["symbol"],
         "magic": state["magic"], "remaining_volume_lots": state["volume"],
         "opened_at": state["opened_at"], "deal_count": state["deal_count"]}
        for state in positions.values()
    ]
    pnl_trades = [trade for trade in closed if trade["pnl_complete"] and trade["net_pnl"] is not None]
    wins = [trade["net_pnl"] for trade in pnl_trades if trade["net_pnl"] > 0]
    losses = [trade["net_pnl"] for trade in pnl_trades if trade["net_pnl"] < 0]
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    equity = peak = max_drawdown = 0.0
    for trade in sorted(pnl_trades, key=lambda item: (item["closed_at"], item["position_id"])):
        equity += trade["net_pnl"]
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "closed_trade_count": len(closed),
        "pnl_complete_trade_count": len(pnl_trades),
        "pnl_incomplete_trade_count": len(closed) - len(pnl_trades),
        "unmatched_deal_count": unmatched,
        "overclose_or_ambiguous_count": incomplete,
        "open_position_count": len(open_positions),
        "missing_cash_deal_count": missing_cash_deals,
        "net_realized_pnl": sum(t["net_pnl"] for t in pnl_trades),
        "account_currency": None,
        "win_rate_pct": (len(wins) / len(pnl_trades) * 100.0) if pnl_trades else None,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else (None if not wins else None),
        "expectancy_per_trade": (sum(t["net_pnl"] for t in pnl_trades) / len(pnl_trades)) if pnl_trades else None,
        "average_win": (sum(wins) / len(wins)) if wins else None,
        "average_loss": (sum(losses) / len(losses)) if losses else None,
        "max_drawdown_cash": max_drawdown if pnl_trades else None,
        "closed_trades": closed[-500:],
        "open_positions": open_positions[:500],
        "coverage": ("partial" if (len(closed) != len(pnl_trades) or unmatched or incomplete or missing_cash_deals) else ("complete" if pnl_trades else "no_closed_trades")),
        "limitations": [
            "Only broker deals with a POSITION_IDENTIFIER can be attributed.",
            "Open and partially closed positions are excluded from realized trade metrics.",
            "Account currency is supplied by the latest account snapshot; no currency conversion is applied.",
            "Magic number is a grouping key, not proof of strategy attribution.",
            "The MT5 bridge uploads a bounded rolling history window; results are limited to deals actually ingested.",
            "Standalone account-level commission, balance or correction records without a position link are not allocated to individual trades.",
        ],
    }

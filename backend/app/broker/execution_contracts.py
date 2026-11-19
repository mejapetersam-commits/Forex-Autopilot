"""Broker-neutral contracts for a future MT5 adapter.

No implementation in this module connects to a terminal or sends an order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class SymbolSpecification:
    symbol: str
    digits: int
    point: float
    tick_size: float
    tick_value_per_lot: float
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level_points: int
    freeze_level_points: int
    trade_allowed: bool
    quote_currency: str
    account_currency: str

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("Broker symbol is required.")
        if not 0 <= self.digits <= 10:
            raise ValueError("Invalid symbol digits.")
        for name in ("point", "tick_size", "tick_value_per_lot", "contract_size",
                     "volume_min", "volume_max", "volume_step"):
            value = float(getattr(self, name))
            if value <= 0:
                raise ValueError(f"{name} must be positive.")
        if self.volume_max < self.volume_min:
            raise ValueError("Broker maximum volume is below minimum volume.")
        if self.stops_level_points < 0 or self.freeze_level_points < 0:
            raise ValueError("Broker stop/freeze levels cannot be negative.")
        if not self.quote_currency or not self.account_currency:
            raise ValueError("Quote and account currencies are required.")


@dataclass(frozen=True)
class BrokerAccountState:
    server: str
    account_currency: str
    balance: float
    equity: float
    margin: float
    free_margin: float
    observed_at: datetime


@dataclass(frozen=True)
class ProtectedOrderRequest:
    symbol: str
    side: str
    volume_lots: float
    stop_loss: float
    take_profit: float
    client_intent_id: str


@dataclass(frozen=True)
class BrokerOrderState:
    broker_order_id: str
    client_intent_id: str
    status: str
    filled_volume: float
    average_fill_price: float | None
    observed_at: datetime


class BrokerExecutionAdapter(Protocol):
    """Contract only. A real adapter must be separately audited and demo-tested."""

    def account_state(self) -> BrokerAccountState: ...

    def symbol_specification(self, symbol: str) -> SymbolSpecification: ...

    def open_positions(self) -> list[dict]: ...

    def submit_protected_order(self, request: ProtectedOrderRequest) -> BrokerOrderState: ...

    def order_state(self, broker_order_id: str) -> BrokerOrderState: ...

    def cancel_order(self, broker_order_id: str) -> BrokerOrderState: ...

    def close_position(self, position_ticket: str) -> BrokerOrderState: ...

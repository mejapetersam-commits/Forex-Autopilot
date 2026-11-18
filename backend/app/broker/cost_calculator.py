
from decimal import Decimal
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field

from app.broker.models import BrokerInstrumentSpecs


class TransactionCostEstimate(BaseModel):
    """
    Estimated transaction costs expressed in account currency.
    """

    model_config = ConfigDict(extra="forbid")

    spread_cost: float = Field(ge=0)
    commission_cost: float = Field(ge=0)
    slippage_cost: float = Field(ge=0)
    total_cost: float = Field(ge=0)

    volume: float = Field(gt=0)
    account_currency: str


def estimate_transaction_costs(
    specs: BrokerInstrumentSpecs,
    volume: float,
    commission_per_lot_per_side: float,
    slippage_ticks_per_side: float,
    include_spread: bool = True,
) -> TransactionCostEstimate:
    """
    Estimate the transaction costs for opening and closing a trade.

    All monetary costs must be expressed in the account currency.

    commission_per_lot_per_side:
        Commission charged for one side of a trade per full lot.

    slippage_ticks_per_side:
        Estimated adverse execution slippage, in ticks, per side.

    include_spread:
        Include spread cost when the planned entry/stop calculation
        is based on a mid-price rather than executable bid/ask prices.

    IMPORTANT:
        Do not include spread twice. If the stop-distance calculation
        already uses executable entry prices, set include_spread=False.
    """

    inputs = {
        "volume": volume,
        "commission_per_lot_per_side": commission_per_lot_per_side,
        "slippage_ticks_per_side": slippage_ticks_per_side,
    }

    for name, value in inputs.items():
        if not isfinite(value):
            raise ValueError(f"{name} must be a finite number.")

    if volume <= 0:
        raise ValueError("Volume must be greater than zero.")

    if commission_per_lot_per_side < 0:
        raise ValueError("Commission cannot be negative.")

    if slippage_ticks_per_side < 0:
        raise ValueError("Slippage cannot be negative.")

    trade_volume = Decimal(str(volume))
    commission_per_side = Decimal(
        str(commission_per_lot_per_side)
    )
    slippage_per_side = Decimal(
        str(slippage_ticks_per_side)
    )

    minimum_volume = Decimal(str(specs.volume_min))
    maximum_volume = Decimal(str(specs.volume_max))
    volume_step = Decimal(str(specs.volume_step))

    # Validate broker volume limits.
    if trade_volume < minimum_volume:
        raise ValueError(
            "Trade volume is below the broker minimum."
        )

    if trade_volume > maximum_volume:
        raise ValueError(
            "Trade volume exceeds the broker maximum."
        )

    # Validate volume increments, anchored at the broker minimum.
    volume_steps = (
        (trade_volume - minimum_volume) / volume_step
    )

    if volume_steps != volume_steps.to_integral_value():
        raise ValueError(
            "Trade volume does not match the broker volume step."
        )

    tick_size = Decimal(str(specs.tick_size))
    tick_value_loss = Decimal(str(specs.tick_value_loss))

    bid = Decimal(str(specs.bid))
    ask = Decimal(str(specs.ask))

    if ask < bid:
        raise ValueError("Ask price cannot be below bid price.")

    if tick_size <= 0 or tick_value_loss <= 0:
        raise ValueError(
            "Tick size and loss tick value must be positive."
        )

    # Calculate spread cost.
    spread_cost = Decimal("0")

    if include_spread:
        spread_ticks = (ask - bid) / tick_size

        spread_cost = (
            spread_ticks
            * tick_value_loss
            * trade_volume
        )

    # Calculate opening and closing commission.
    commission_cost = (
        commission_per_side
        * Decimal("2")
        * trade_volume
    )

    # Calculate adverse slippage on opening and closing.
    slippage_cost = (
        slippage_per_side
        * Decimal("2")
        * tick_value_loss
        * trade_volume
    )

    total_cost = (
        spread_cost
        + commission_cost
        + slippage_cost
    )

    return TransactionCostEstimate(
        spread_cost=float(spread_cost),
        commission_cost=float(commission_cost),
        slippage_cost=float(slippage_cost),
        total_cost=float(total_cost),
        volume=float(trade_volume),
        account_currency=specs.account_currency,
    )

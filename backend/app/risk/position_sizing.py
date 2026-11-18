
from decimal import Decimal, ROUND_FLOOR
from math import isfinite

from pydantic import BaseModel

from app.risk.risk_config import RiskConfig
from app.broker.models import BrokerInstrumentSpecs
from app.broker.cost_calculator import estimate_transaction_costs
from app.broker.specifications import BrokerSpecificationsValidator


class PositionSizingResult(BaseModel):
    accepted: bool
    risk_amount: float
    risk_per_lot: float
    raw_volume: float
    volume: float
    estimated_loss: float
    reason: str


class CostAdjustedPositionSizingResult(BaseModel):
    accepted: bool
    risk_amount: float
    stop_loss_per_lot: float
    transaction_cost_per_lot: float
    total_risk_per_lot: float
    raw_volume: float
    volume: float
    estimated_stop_loss: float
    estimated_transaction_cost: float
    estimated_total_loss: float
    account_currency: str
    reason: str


def _validate_positive_finite(name: str, value: float) -> None:
    if not isfinite(value) or value <= 0:
        raise ValueError(
            f"{name} must be a finite number greater than zero."
        )


def calculate_position_size(
    equity: float,
    stop_distance: float,
    tick_size: float,
    tick_value_per_lot: float,
    volume_min: float,
    volume_max: float,
    volume_step: float,
    risk_config: RiskConfig,
) -> PositionSizingResult:
    """
    Calculate trade volume using account equity and stop-loss distance.

    This original calculation does not include transaction costs.
    Use calculate_position_size_with_costs() when costs must be included.
    """

    values = {
        "equity": equity,
        "stop_distance": stop_distance,
        "tick_size": tick_size,
        "tick_value_per_lot": tick_value_per_lot,
        "volume_min": volume_min,
        "volume_max": volume_max,
        "volume_step": volume_step,
    }

    for name, value in values.items():
        _validate_positive_finite(name, value)

    if volume_max < volume_min:
        raise ValueError("Maximum volume cannot be below minimum volume.")

    if volume_step > volume_max:
        raise ValueError("Volume step cannot exceed maximum volume.")

    risk_amount = (
        Decimal(str(equity))
        * Decimal(str(risk_config.risk_per_trade_pct))
        / Decimal("100")
    )

    ticks_to_stop = (
        Decimal(str(stop_distance))
        / Decimal(str(tick_size))
    )

    risk_per_lot = (
        ticks_to_stop
        * Decimal(str(tick_value_per_lot))
    )

    raw_volume = risk_amount / risk_per_lot

    max_volume = Decimal(str(volume_max))
    min_volume = Decimal(str(volume_min))
    step = Decimal(str(volume_step))

    capped_volume = min(raw_volume, max_volume)

    volume = (
        (capped_volume / step).to_integral_value(
            rounding=ROUND_FLOOR
        )
        * step
    )

    if volume < min_volume:
        return PositionSizingResult(
            accepted=False,
            risk_amount=float(risk_amount),
            risk_per_lot=float(risk_per_lot),
            raw_volume=float(raw_volume),
            volume=0.0,
            estimated_loss=0.0,
            reason="Minimum broker volume exceeds the permitted risk.",
        )

    estimated_loss = volume * risk_per_lot

    return PositionSizingResult(
        accepted=True,
        risk_amount=float(risk_amount),
        risk_per_lot=float(risk_per_lot),
        raw_volume=float(raw_volume),
        volume=float(volume),
        estimated_loss=float(estimated_loss),
        reason="Position size calculated successfully.",
    )


def calculate_position_size_with_costs(
    equity: float,
    stop_distance: float,
    specs: BrokerInstrumentSpecs,
    commission_per_lot_per_side: float,
    slippage_ticks_per_side: float,
    risk_config: RiskConfig,
    include_spread: bool = True,
) -> CostAdjustedPositionSizingResult:
    """
    Calculate position size while including estimated transaction costs.

    The total projected loss includes:
    - Stop-loss exposure.
    - Spread, when include_spread=True.
    - Opening and closing commission.
    - Estimated opening and closing slippage.

    All monetary values must be in the account currency.

    stop_distance must be expressed in the same price units as tick_size.

    This function calculates position size only. It does not place trades.
    """

    _validate_positive_finite("equity", equity)
    _validate_positive_finite("stop_distance", stop_distance)

    if not isfinite(commission_per_lot_per_side):
        raise ValueError(
            "Commission must be a finite number."
        )

    if commission_per_lot_per_side < 0:
        raise ValueError("Commission cannot be negative.")

    if not isfinite(slippage_ticks_per_side):
        raise ValueError(
            "Slippage must be a finite number."
        )

    if slippage_ticks_per_side < 0:
        raise ValueError("Slippage cannot be negative.")

    # Validate broker specifications before using them.
    BrokerSpecificationsValidator.validate(specs)

    # Convert numerical inputs to Decimal for safer calculations.
    equity_decimal = Decimal(str(equity))
    stop_decimal = Decimal(str(stop_distance))
    tick_size = Decimal(str(specs.tick_size))
    tick_value_loss = Decimal(str(specs.tick_value_loss))

    commission = Decimal(str(commission_per_lot_per_side))
    slippage = Decimal(str(slippage_ticks_per_side))

    volume_min = Decimal(str(specs.volume_min))
    volume_max = Decimal(str(specs.volume_max))
    volume_step = Decimal(str(specs.volume_step))

    risk_percentage = Decimal(
        str(risk_config.risk_per_trade_pct)
    )

    risk_amount = (
        equity_decimal
        * risk_percentage
        / Decimal("100")
    )

    # Calculate stop-loss exposure for one full lot.
    stop_loss_per_lot = (
        stop_decimal / tick_size
    ) * tick_value_loss

    # Calculate estimated transaction costs for one full lot.
    spread_cost_per_lot = Decimal("0")

    if include_spread:
        spread_ticks = (
            Decimal(str(specs.ask))
            - Decimal(str(specs.bid))
        ) / tick_size

        spread_cost_per_lot = (
            spread_ticks * tick_value_loss
        )

    commission_cost_per_lot = commission * Decimal("2")

    slippage_cost_per_lot = (
        slippage
        * Decimal("2")
        * tick_value_loss
    )

    transaction_cost_per_lot = (
        spread_cost_per_lot
        + commission_cost_per_lot
        + slippage_cost_per_lot
    )

    # Total risk per full lot.
    total_risk_per_lot = (
        stop_loss_per_lot
        + transaction_cost_per_lot
    )

    if total_risk_per_lot <= 0:
        raise ValueError(
            "Total risk per lot must be greater than zero."
        )

    # Calculate theoretical volume using the complete risk estimate.
    raw_volume = risk_amount / total_risk_per_lot

    # Determine the largest valid broker volume.
    maximum_steps = (
        (volume_max - volume_min) / volume_step
    ).to_integral_value(rounding=ROUND_FLOOR)

    effective_maximum = (
        volume_min + maximum_steps * volume_step
    )

    capped_volume = min(raw_volume, effective_maximum)

    # Broker volume increments are anchored at minimum volume.
    if capped_volume < volume_min:
        return CostAdjustedPositionSizingResult(
            accepted=False,
            risk_amount=float(risk_amount),
            stop_loss_per_lot=float(stop_loss_per_lot),
            transaction_cost_per_lot=float(
                transaction_cost_per_lot
            ),
            total_risk_per_lot=float(total_risk_per_lot),
            raw_volume=float(raw_volume),
            volume=0.0,
            estimated_stop_loss=0.0,
            estimated_transaction_cost=0.0,
            estimated_total_loss=0.0,
            account_currency=specs.account_currency,
            reason=(
                "Minimum broker volume exceeds the permitted "
                "risk after transaction costs."
            ),
        )

    volume_steps = (
        (capped_volume - volume_min) / volume_step
    ).to_integral_value(rounding=ROUND_FLOOR)

    volume = volume_min + volume_steps * volume_step

    # Calculate the final stop-loss exposure.
    estimated_stop_loss = stop_loss_per_lot * volume

    # Use the existing transaction cost calculator for the final volume.
    costs = estimate_transaction_costs(
        specs=specs,
        volume=float(volume),
        commission_per_lot_per_side=float(commission),
        slippage_ticks_per_side=float(slippage),
        include_spread=include_spread,
    )

    estimated_transaction_cost = Decimal(
        str(costs.total_cost)
    )

    estimated_total_loss = (
        estimated_stop_loss
        + estimated_transaction_cost
    )

    # Final independent risk-budget check.
    if estimated_total_loss > risk_amount:
        return CostAdjustedPositionSizingResult(
            accepted=False,
            risk_amount=float(risk_amount),
            stop_loss_per_lot=float(stop_loss_per_lot),
            transaction_cost_per_lot=float(
                transaction_cost_per_lot
            ),
            total_risk_per_lot=float(total_risk_per_lot),
            raw_volume=float(raw_volume),
            volume=0.0,
            estimated_stop_loss=0.0,
            estimated_transaction_cost=0.0,
            estimated_total_loss=0.0,
            account_currency=specs.account_currency,
            reason=(
                "Calculated volume exceeds the permitted risk "
                "after transaction costs."
            ),
        )

    return CostAdjustedPositionSizingResult(
        accepted=True,
        risk_amount=float(risk_amount),
        stop_loss_per_lot=float(stop_loss_per_lot),
        transaction_cost_per_lot=float(
            transaction_cost_per_lot
        ),
        total_risk_per_lot=float(total_risk_per_lot),
        raw_volume=float(raw_volume),
        volume=float(volume),
        estimated_stop_loss=float(estimated_stop_loss),
        estimated_transaction_cost=float(
            estimated_transaction_cost
        ),
        estimated_total_loss=float(estimated_total_loss),
        account_currency=specs.account_currency,
        reason=(
            "Cost-adjusted position size calculated successfully."
        ),
    )

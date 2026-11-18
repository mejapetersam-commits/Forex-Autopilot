
from decimal import Decimal, ROUND_FLOOR

from pydantic import BaseModel, Field

from app.risk.risk_config import RiskConfig


class PositionSizingResult(BaseModel):
    accepted: bool
    risk_amount: float
    risk_per_lot: float
    raw_volume: float
    volume: float
    estimated_loss: float
    reason: str


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
    Calculate a trade volume using account equity and stop-loss distance.

    tick_value_per_lot must be expressed in the account's deposit currency.
    All price distances must use the same price units as tick_size.

    This is a calculation module only. It does not place trades.
    """

    # Validate numerical inputs
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
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero.")

    if volume_max < volume_min:
        raise ValueError("Maximum volume cannot be below minimum volume.")

    # Calculate the maximum monetary risk allowed
    risk_amount = (
        Decimal(str(equity))
        * Decimal(str(risk_config.risk_per_trade_pct))
        / Decimal("100")
    )

    # Calculate the monetary risk of one full lot
    ticks_to_stop = (
        Decimal(str(stop_distance))
        / Decimal(str(tick_size))
    )

    risk_per_lot = (
        ticks_to_stop
        * Decimal(str(tick_value_per_lot))
    )

    # Calculate theoretical position volume
    raw_volume = risk_amount / risk_per_lot

    # Respect broker volume limits
    max_volume = Decimal(str(volume_max))
    min_volume = Decimal(str(volume_min))
    step = Decimal(str(volume_step))

    capped_volume = min(raw_volume, max_volume)

    # Always round DOWN to avoid exceeding planned risk
    volume = (
        (capped_volume / step).to_integral_value(
            rounding=ROUND_FLOOR
        )
        * step
    )

    # Reject if the minimum permitted volume is too risky
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

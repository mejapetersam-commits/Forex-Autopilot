
import pytest

from app.broker.models import BrokerInstrumentSpecs
from app.risk.position_sizing import (
    calculate_position_size_with_costs,
)
from app.risk.risk_config import RiskConfig


@pytest.fixture
def eurusd_specs():
    return BrokerInstrumentSpecs(
        symbol="EURUSD",
        base_currency="EUR",
        quote_currency="USD",
        account_currency="USD",
        contract_size=100000,
        tick_size=0.00001,
        tick_value_profit=1.0,
        tick_value_loss=1.0,
        volume_min=0.01,
        volume_max=100,
        volume_step=0.01,
        bid=1.08500,
        ask=1.08510,
    )


@pytest.fixture
def risk_config():
    return RiskConfig(
        risk_per_trade_pct=0.25,
        max_daily_loss_pct=1.0,
        max_drawdown_pct=5.0,
    )


def test_calculates_position_size_including_all_costs(
    eurusd_specs,
    risk_config,
):
    result = calculate_position_size_with_costs(
        equity=10000,
        stop_distance=0.001,
        specs=eurusd_specs,
        commission_per_lot_per_side=3.50,
        slippage_ticks_per_side=1,
        risk_config=risk_config,
    )

    assert result.accepted is True
    assert result.risk_amount == pytest.approx(25.0)
    assert result.stop_loss_per_lot == pytest.approx(100.0)
    assert result.transaction_cost_per_lot == pytest.approx(19.0)
    assert result.volume == pytest.approx(0.21)
    assert result.estimated_stop_loss == pytest.approx(21.0)
    assert result.estimated_transaction_cost == pytest.approx(3.99)
    assert result.estimated_total_loss == pytest.approx(24.99)
    assert result.estimated_total_loss <= result.risk_amount


def test_excludes_spread_when_already_accounted_for(
    eurusd_specs,
    risk_config,
):
    result = calculate_position_size_with_costs(
        equity=10000,
        stop_distance=0.001,
        specs=eurusd_specs,
        commission_per_lot_per_side=3.50,
        slippage_ticks_per_side=1,
        risk_config=risk_config,
        include_spread=False,
    )

    assert result.accepted is True
    assert result.transaction_cost_per_lot == pytest.approx(9.0)
    assert result.volume == pytest.approx(0.22)
    assert result.estimated_total_loss <= result.risk_amount


def test_rejects_trade_when_minimum_volume_exceeds_risk_budget(
    eurusd_specs,
    risk_config,
):
    result = calculate_position_size_with_costs(
        equity=400,
        stop_distance=0.001,
        specs=eurusd_specs,
        commission_per_lot_per_side=3.50,
        slippage_ticks_per_side=1,
        risk_config=risk_config,
    )

    assert result.accepted is False
    assert result.volume == 0
    assert result.estimated_total_loss == 0
    assert "Minimum broker volume" in result.reason


def test_rejects_non_finite_equity(
    eurusd_specs,
    risk_config,
):
    with pytest.raises(ValueError, match="equity"):
        calculate_position_size_with_costs(
            equity=float("inf"),
            stop_distance=0.001,
            specs=eurusd_specs,
            commission_per_lot_per_side=3.50,
            slippage_ticks_per_side=1,
            risk_config=risk_config,
        )


def test_rejects_negative_commission(
    eurusd_specs,
    risk_config,
):
    with pytest.raises(ValueError, match="Commission"):
        calculate_position_size_with_costs(
            equity=10000,
            stop_distance=0.001,
            specs=eurusd_specs,
            commission_per_lot_per_side=-1,
            slippage_ticks_per_side=1,
            risk_config=risk_config,
        )


def test_rejects_negative_slippage(
    eurusd_specs,
    risk_config,
):
    with pytest.raises(ValueError, match="Slippage"):
        calculate_position_size_with_costs(
            equity=10000,
            stop_distance=0.001,
            specs=eurusd_specs,
            commission_per_lot_per_side=3.50,
            slippage_ticks_per_side=-1,
            risk_config=risk_config,
        )

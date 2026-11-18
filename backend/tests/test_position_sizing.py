
import pytest

from app.risk.risk_config import RiskConfig
from app.risk.position_sizing import calculate_position_size


@pytest.fixture
def risk_config():
    return RiskConfig(risk_per_trade_pct=0.25)


def test_calculates_correct_position_size(risk_config):
    result = calculate_position_size(
        equity=10000,
        stop_distance=0.002,
        tick_size=0.00001,
        tick_value_per_lot=1,
        volume_min=0.01,
        volume_max=100,
        volume_step=0.01,
        risk_config=risk_config,
    )

    assert result.accepted is True
    assert result.volume == 0.12
    assert result.estimated_loss == 24
    assert result.risk_amount == 25


def test_rejects_position_below_minimum_volume(risk_config):
    result = calculate_position_size(
        equity=100,
        stop_distance=0.01,
        tick_size=0.00001,
        tick_value_per_lot=1,
        volume_min=0.01,
        volume_max=100,
        volume_step=0.01,
        risk_config=risk_config,
    )

    assert result.accepted is False
    assert result.volume == 0
    assert "Minimum broker volume" in result.reason


def test_caps_volume_at_broker_maximum(risk_config):
    result = calculate_position_size(
        equity=1000000,
        stop_distance=0.0001,
        tick_size=0.00001,
        tick_value_per_lot=1,
        volume_min=0.01,
        volume_max=2,
        volume_step=0.01,
        risk_config=risk_config,
    )

    assert result.accepted is True
    assert result.volume == 2
    assert result.estimated_loss <= result.risk_amount


@pytest.mark.parametrize(
    "field,value",
    [
        ("equity", 0),
        ("stop_distance", 0),
        ("tick_size", 0),
        ("tick_value_per_lot", 0),
        ("volume_min", 0),
        ("volume_max", 0),
        ("volume_step", 0),
    ],
)
def test_rejects_invalid_inputs(risk_config, field, value):
    parameters = {
        "equity": 10000,
        "stop_distance": 0.002,
        "tick_size": 0.00001,
        "tick_value_per_lot": 1,
        "volume_min": 0.01,
        "volume_max": 100,
        "volume_step": 0.01,
        "risk_config": risk_config,
    }

    parameters[field] = value

    with pytest.raises(ValueError):
        calculate_position_size(**parameters)


def test_rejects_maximum_volume_below_minimum(risk_config):
    with pytest.raises(ValueError):
        calculate_position_size(
            equity=10000,
            stop_distance=0.002,
            tick_size=0.00001,
            tick_value_per_lot=1,
            volume_min=1,
            volume_max=0.5,
            volume_step=0.01,
            risk_config=risk_config,
        )

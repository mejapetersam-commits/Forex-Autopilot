
import pytest

from app.broker.models import BrokerInstrumentSpecs
from app.broker.cost_calculator import estimate_transaction_costs


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


def test_calculates_all_transaction_costs(eurusd_specs):
    result = estimate_transaction_costs(
        specs=eurusd_specs,
        volume=0.10,
        commission_per_lot_per_side=3.50,
        slippage_ticks_per_side=1,
    )

    assert result.spread_cost == pytest.approx(1.00)
    assert result.commission_cost == pytest.approx(0.70)
    assert result.slippage_cost == pytest.approx(0.20)
    assert result.total_cost == pytest.approx(1.90)
    assert result.account_currency == "USD"


def test_excludes_spread_when_already_accounted_for(eurusd_specs):
    result = estimate_transaction_costs(
        specs=eurusd_specs,
        volume=0.10,
        commission_per_lot_per_side=3.50,
        slippage_ticks_per_side=1,
        include_spread=False,
    )

    assert result.spread_cost == 0
    assert result.total_cost == pytest.approx(0.90)


def test_rejects_volume_below_broker_minimum(eurusd_specs):
    with pytest.raises(ValueError, match="below the broker minimum"):
        estimate_transaction_costs(
            specs=eurusd_specs,
            volume=0.001,
            commission_per_lot_per_side=3.50,
            slippage_ticks_per_side=1,
        )


def test_rejects_volume_above_broker_maximum(eurusd_specs):
    with pytest.raises(ValueError, match="exceeds the broker maximum"):
        estimate_transaction_costs(
            specs=eurusd_specs,
            volume=101,
            commission_per_lot_per_side=3.50,
            slippage_ticks_per_side=1,
        )


def test_rejects_invalid_volume_increment(eurusd_specs):
    with pytest.raises(ValueError, match="volume step"):
        estimate_transaction_costs(
            specs=eurusd_specs,
            volume=0.015,
            commission_per_lot_per_side=3.50,
            slippage_ticks_per_side=1,
        )


def test_rejects_negative_commission(eurusd_specs):
    with pytest.raises(ValueError, match="Commission"):
        estimate_transaction_costs(
            specs=eurusd_specs,
            volume=0.10,
            commission_per_lot_per_side=-1,
            slippage_ticks_per_side=1,
        )


def test_rejects_negative_slippage(eurusd_specs):
    with pytest.raises(ValueError, match="Slippage"):
        estimate_transaction_costs(
            specs=eurusd_specs,
            volume=0.10,
            commission_per_lot_per_side=3.50,
            slippage_ticks_per_side=-1,
        )


def test_rejects_zero_volume(eurusd_specs):
    with pytest.raises(ValueError, match="Volume"):
        estimate_transaction_costs(
            specs=eurusd_specs,
            volume=0,
            commission_per_lot_per_side=3.50,
            slippage_ticks_per_side=1,
        )


def test_rejects_infinite_volume(eurusd_specs):
    with pytest.raises(ValueError, match="finite number"):
        estimate_transaction_costs(
            specs=eurusd_specs,
            volume=float("inf"),
            commission_per_lot_per_side=3.50,
            slippage_ticks_per_side=1,
        )

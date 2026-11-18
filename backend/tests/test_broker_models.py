
import pytest
from pydantic import ValidationError

from app.broker.models import BrokerInstrumentSpecs


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


def test_creates_valid_broker_specs(eurusd_specs):
    assert eurusd_specs.symbol == "EURUSD"
    assert eurusd_specs.contract_size == 100000


def test_calculates_spread(eurusd_specs):
    assert round(eurusd_specs.spread, 5) == 0.00010


def test_calculates_spread_in_ticks(eurusd_specs):
    assert eurusd_specs.spread_in_ticks == 10


def test_validates_market_spread(eurusd_specs):
    assert eurusd_specs.is_valid_spread is True


def test_rejects_invalid_tick_size():
    with pytest.raises(ValidationError):
        BrokerInstrumentSpecs(
            symbol="EURUSD",
            base_currency="EUR",
            quote_currency="USD",
            account_currency="USD",
            contract_size=100000,
            tick_size=0,
            tick_value_profit=1.0,
            tick_value_loss=1.0,
            volume_min=0.01,
            volume_max=100,
            volume_step=0.01,
            bid=1.08500,
            ask=1.08510,
        )


def test_rejects_ask_below_bid(eurusd_specs):
    invalid_specs = eurusd_specs.model_copy(
        update={"bid": 1.08510, "ask": 1.08500}
    )

    with pytest.raises(ValueError):
        invalid_specs.validate_market_prices()


def test_rejects_maximum_volume_below_minimum(eurusd_specs):
    invalid_specs = eurusd_specs.model_copy(
        update={"volume_min": 1.0, "volume_max": 0.5}
    )

    with pytest.raises(ValueError):
        invalid_specs.validate_volume_limits()

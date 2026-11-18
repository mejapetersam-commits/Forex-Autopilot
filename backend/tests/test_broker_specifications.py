
import pytest

from app.broker.models import BrokerInstrumentSpecs
from app.broker.specifications import BrokerSpecificationsValidator


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


def test_accepts_valid_broker_specifications(eurusd_specs):
    result = BrokerSpecificationsValidator.validate(eurusd_specs)

    assert result.symbol == "EURUSD"


def test_rejects_ask_below_bid(eurusd_specs):
    invalid_specs = eurusd_specs.model_copy(
        update={"bid": 1.08510, "ask": 1.08500}
    )

    with pytest.raises(ValueError, match="Ask price"):
        BrokerSpecificationsValidator.validate(invalid_specs)


def test_rejects_zero_spread(eurusd_specs):
    invalid_specs = eurusd_specs.model_copy(
        update={"bid": 1.08500, "ask": 1.08500}
    )

    with pytest.raises(ValueError, match="Spread"):
        BrokerSpecificationsValidator.validate(invalid_specs)


def test_rejects_invalid_volume_limits(eurusd_specs):
    invalid_specs = eurusd_specs.model_copy(
        update={"volume_min": 1.0, "volume_max": 0.5}
    )

    with pytest.raises(ValueError, match="Maximum volume"):
        BrokerSpecificationsValidator.validate(invalid_specs)


def test_rejects_volume_step_above_maximum(eurusd_specs):
    invalid_specs = eurusd_specs.model_copy(
        update={"volume_step": 101}
    )

    with pytest.raises(ValueError, match="Volume step"):
        BrokerSpecificationsValidator.validate(invalid_specs)


def test_accepts_matching_symbol(eurusd_specs):
    BrokerSpecificationsValidator.validate_symbol(
        eurusd_specs,
        "EURUSD",
    )


def test_rejects_mismatched_symbol(eurusd_specs):
    with pytest.raises(ValueError, match="Symbol mismatch"):
        BrokerSpecificationsValidator.validate_symbol(
            eurusd_specs,
            "GBPUSD",
        )

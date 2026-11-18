
from app.broker.models import BrokerInstrumentSpecs


class BrokerSpecificationsValidator:
    """
    Validates broker-provided instrument specifications
    before they are used by the risk management engine.
    """

    @staticmethod
    def validate(specs: BrokerInstrumentSpecs) -> BrokerInstrumentSpecs:
        """
        Validate instrument specifications and return them
        only when all checks pass.
        """

        # Check market prices
        specs.validate_market_prices()

        # Check broker volume limits
        specs.validate_volume_limits()

        # Check that the spread is positive
        if specs.spread <= 0:
            raise ValueError(
                "Spread must be greater than zero."
            )

        # Check volume step consistency
        if specs.volume_step > specs.volume_max:
            raise ValueError(
                "Volume step cannot exceed maximum volume."
            )

        # Check tick values
        if specs.tick_value_profit <= 0:
            raise ValueError(
                "Profit tick value must be greater than zero."
            )

        if specs.tick_value_loss <= 0:
            raise ValueError(
                "Loss tick value must be greater than zero."
            )

        return specs

    @staticmethod
    def validate_symbol(
        specs: BrokerInstrumentSpecs,
        expected_symbol: str,
    ) -> None:
        """
        Ensure the broker returned specifications
        for the requested trading instrument.
        """

        if specs.symbol.upper() != expected_symbol.upper():
            raise ValueError(
                f"Symbol mismatch: expected {expected_symbol}, "
                f"received {specs.symbol}."
            )

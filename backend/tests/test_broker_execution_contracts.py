import pytest

from app.broker.execution_contracts import SymbolSpecification


def valid_spec():
    return SymbolSpecification(
        symbol="EURUSDm", digits=5, point=0.00001, tick_size=0.00001,
        tick_value_per_lot=1.0, contract_size=100000,
        volume_min=0.01, volume_max=100, volume_step=0.01,
        stops_level_points=10, freeze_level_points=0, trade_allowed=True,
        quote_currency="USD", account_currency="USD",
    )


def test_symbol_specification_accepts_complete_broker_metadata():
    spec = valid_spec()
    assert spec.symbol == "EURUSDm"
    assert spec.volume_step == 0.01


def test_symbol_specification_rejects_missing_or_invalid_contract_metadata():
    from dataclasses import replace
    with pytest.raises(ValueError, match="tick_value_per_lot"):
        replace(valid_spec(), tick_value_per_lot=0)
    with pytest.raises(ValueError, match="maximum volume"):
        replace(valid_spec(), volume_max=0.001)

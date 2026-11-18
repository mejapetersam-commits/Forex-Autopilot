
import pytest
from pydantic import ValidationError

from app.risk.risk_config import RiskConfig


def test_default_currency_exposure_limit_is_200_percent():
    config = RiskConfig()

    assert config.max_currency_exposure_pct == 200.0


def test_accepts_custom_currency_exposure_limit():
    config = RiskConfig(max_currency_exposure_pct=150.0)

    assert config.max_currency_exposure_pct == 150.0


def test_accepts_maximum_currency_exposure_limit():
    config = RiskConfig(max_currency_exposure_pct=1000.0)

    assert config.max_currency_exposure_pct == 1000.0


@pytest.mark.parametrize(
    "invalid_limit",
    [0, -1, -100, 1001],
)
def test_rejects_invalid_currency_exposure_limit(invalid_limit):
    with pytest.raises(ValidationError):
        RiskConfig(max_currency_exposure_pct=invalid_limit)


def test_rejects_unknown_configuration_fields():
    with pytest.raises(ValidationError):
        RiskConfig(unknown_setting=100)


def test_existing_risk_defaults_remain_unchanged():
    config = RiskConfig()

    assert config.risk_per_trade_pct == 0.25
    assert config.max_daily_loss_pct == 1.0
    assert config.max_drawdown_pct == 5.0
    assert config.max_open_positions == 2
    assert config.require_stop_loss is True
    assert config.allow_martingale is False
    assert config.allow_grid_trading is False
    assert config.trading_enabled is False


def test_currency_exposure_limit_does_not_enable_trading():
    config = RiskConfig(max_currency_exposure_pct=200.0)

    assert config.trading_enabled is False

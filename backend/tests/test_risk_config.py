
import pytest
from pydantic import ValidationError

from app.risk.risk_config import RiskConfig


def test_default_risk_configuration():
    config = RiskConfig()

    assert config.risk_per_trade_pct == 0.25
    assert config.max_daily_loss_pct == 1.0
    assert config.max_drawdown_pct == 5.0
    assert config.max_open_positions == 2
    assert config.require_stop_loss is True
    assert config.allow_martingale is False
    assert config.allow_grid_trading is False
    assert config.trading_enabled is False


def test_custom_risk_configuration():
    config = RiskConfig(
        risk_per_trade_pct=0.5,
        max_daily_loss_pct=2.0,
        max_drawdown_pct=6.0,
        max_open_positions=3,
    )

    assert config.risk_per_trade_pct == 0.5
    assert config.max_open_positions == 3


def test_reject_risk_above_allowed_limit():
    with pytest.raises(ValidationError):
        RiskConfig(risk_per_trade_pct=1.5)


def test_reject_martingale():
    with pytest.raises(ValidationError):
        RiskConfig(allow_martingale=True)


def test_reject_grid_trading():
    with pytest.raises(ValidationError):
        RiskConfig(allow_grid_trading=True)


def test_reject_disabled_stop_loss():
    with pytest.raises(ValidationError):
        RiskConfig(require_stop_loss=False)


def test_reject_daily_loss_above_drawdown():
    with pytest.raises(ValidationError):
        RiskConfig(
            max_daily_loss_pct=6.0,
            max_drawdown_pct=5.0,
        )


def test_reject_extra_configuration_fields():
    with pytest.raises(ValidationError):
        RiskConfig(unapproved_setting=True)

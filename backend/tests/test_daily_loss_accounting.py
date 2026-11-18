
import pytest

from app.portfolio.risk_manager import (
    PortfolioSnapshot,
    PortfolioRiskManager,
)
from app.risk.risk_config import RiskConfig


@pytest.fixture
def risk_config():
    return RiskConfig(
        risk_per_trade_pct=0.25,
        max_daily_loss_pct=1.0,
        max_drawdown_pct=5.0,
        max_open_positions=2,
    )


def test_floating_loss_increases_actual_daily_loss(risk_config):
    snapshot = PortfolioSnapshot(
        current_equity=9900,
        day_start_equity=10000,
        peak_equity=10000,
        daily_realized_loss=20,
        daily_floating_pnl=-30,
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=5,
        risk_config=risk_config,
    )

    assert result.actual_daily_loss == pytest.approx(50)
    assert result.daily_realized_loss == pytest.approx(20)
    assert result.daily_floating_pnl == pytest.approx(-30)
    assert result.projected_daily_loss == pytest.approx(55)


def test_floating_profit_offsets_realized_loss(risk_config):
    snapshot = PortfolioSnapshot(
        current_equity=10050,
        day_start_equity=10000,
        peak_equity=10050,
        daily_realized_loss=80,
        daily_floating_pnl=30,
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=5,
        risk_config=risk_config,
    )

    assert result.actual_daily_loss == pytest.approx(50)
    assert result.projected_daily_loss == pytest.approx(55)
    assert result.approved is True


def test_floating_profit_cannot_create_negative_daily_loss(
    risk_config,
):
    snapshot = PortfolioSnapshot(
        current_equity=10100,
        day_start_equity=10000,
        peak_equity=10100,
        daily_realized_loss=20,
        daily_floating_pnl=50,
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=5,
        risk_config=risk_config,
    )

    assert result.actual_daily_loss == pytest.approx(0)
    assert result.projected_daily_loss == pytest.approx(5)


def test_open_risk_is_separate_from_actual_daily_loss(
    risk_config,
):
    snapshot = PortfolioSnapshot(
        current_equity=10000,
        day_start_equity=10000,
        peak_equity=10000,
        daily_realized_loss=0,
        daily_floating_pnl=0,
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=10,
        risk_config=risk_config,
    )

    assert result.actual_daily_loss == pytest.approx(0)
    assert result.existing_open_risk == pytest.approx(0)
    assert result.proposed_trade_risk == pytest.approx(10)
    assert result.projected_daily_loss == pytest.approx(10)


def test_actual_daily_loss_limit_breach_rejects_trade(
    risk_config,
):
    snapshot = PortfolioSnapshot(
        current_equity=9900,
        day_start_equity=10000,
        peak_equity=10000,
        daily_realized_loss=80,
        daily_floating_pnl=-25,
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=1,
        risk_config=risk_config,
    )

    assert result.actual_daily_loss == pytest.approx(105)
    assert result.approved is False
    assert any(
        "already been reached" in reason.lower()
        for reason in result.reasons
    )


def test_daily_floating_pnl_must_be_finite():
    with pytest.raises(ValueError, match="finite"):
        PortfolioSnapshot(
            current_equity=10000,
            day_start_equity=10000,
            peak_equity=10000,
            daily_realized_loss=0,
            daily_floating_pnl=float("inf"),
        )

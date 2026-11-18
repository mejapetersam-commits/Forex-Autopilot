
import pytest

from app.portfolio.risk_manager import (
    OpenPositionRisk,
    PortfolioSnapshot,
    PortfolioRiskManager,
)
from app.risk.risk_config import RiskConfig


@pytest.fixture
def risk_config():
    return RiskConfig(
        risk_per_trade_pct=1.0,
        max_daily_loss_pct=3.0,
        max_drawdown_pct=5.0,
        max_open_positions=2,
    )


def test_calculates_projected_drawdown_correctly(risk_config):
    snapshot = PortfolioSnapshot(
        current_equity=9700,
        day_start_equity=10000,
        peak_equity=10000,
        daily_realized_loss=0,
        daily_floating_pnl=0,
        open_positions=[
            OpenPositionRisk(
                ticket="1001",
                symbol="EURUSD",
                risk_to_stop=200,
            )
        ],
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=50,
        risk_config=risk_config,
    )

    assert result.projected_equity_after_stops == pytest.approx(9450)
    assert result.projected_drawdown_amount == pytest.approx(550)
    assert result.projected_drawdown_pct == pytest.approx(5.5)
    assert result.approved is False


def test_approves_trade_when_projected_drawdown_is_below_limit(
    risk_config,
):
    snapshot = PortfolioSnapshot(
        current_equity=9800,
        day_start_equity=10000,
        peak_equity=10000,
        daily_realized_loss=0,
        daily_floating_pnl=0,
        open_positions=[
            OpenPositionRisk(
                ticket="1001",
                symbol="EURUSD",
                risk_to_stop=100,
            )
        ],
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=90,
        risk_config=risk_config,
    )

    assert result.current_drawdown_pct == pytest.approx(2.0)
    assert result.projected_drawdown_pct == pytest.approx(3.9)
    assert result.approved is True


def test_rejects_trade_when_projected_drawdown_exceeds_limit(
    risk_config,
):
    snapshot = PortfolioSnapshot(
        current_equity=9700,
        day_start_equity=10000,
        peak_equity=10000,
        daily_realized_loss=0,
        daily_floating_pnl=0,
        open_positions=[
            OpenPositionRisk(
                ticket="1001",
                symbol="EURUSD",
                risk_to_stop=200,
            )
        ],
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=100,
        risk_config=risk_config,
    )

    assert result.projected_drawdown_pct == pytest.approx(6.0)
    assert result.approved is False
    assert any(
        "projected account drawdown" in reason.lower()
        for reason in result.reasons
    )


def test_rejects_trade_when_projected_drawdown_equals_limit(
    risk_config,
):
    snapshot = PortfolioSnapshot(
        current_equity=28800,
        day_start_equity=30000,
        peak_equity=30000,
        daily_realized_loss=0,
        daily_floating_pnl=0,
        open_positions=[
            OpenPositionRisk(
                ticket="1001",
                symbol="EURUSD",
                risk_to_stop=100,
            )
        ],
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=200,
        risk_config=risk_config,
    )

    assert result.current_drawdown_pct == pytest.approx(4.0)
    assert result.projected_drawdown_pct == pytest.approx(5.0)
    assert result.approved is False
    assert any(
        "projected account drawdown" in reason.lower()
        for reason in result.reasons
    )


def test_projected_drawdown_includes_existing_open_risk(
    risk_config,
):
    snapshot = PortfolioSnapshot(
        current_equity=10000,
        day_start_equity=10000,
        peak_equity=10000,
        daily_realized_loss=0,
        daily_floating_pnl=0,
        open_positions=[
            OpenPositionRisk(
                ticket="1001",
                symbol="EURUSD",
                risk_to_stop=150,
            ),
            OpenPositionRisk(
                ticket="1002",
                symbol="GBPUSD",
                risk_to_stop=100,
            ),
        ],
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=10,
        risk_config=risk_config,
    )

    assert result.existing_open_risk == pytest.approx(250)
    assert result.projected_total_open_risk == pytest.approx(260)
    assert result.projected_drawdown_amount == pytest.approx(260)
    assert result.projected_drawdown_pct == pytest.approx(2.6)


def test_projected_drawdown_is_not_negative_when_equity_is_at_peak(
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

    assert result.current_drawdown_amount == pytest.approx(0)
    assert result.projected_drawdown_amount == pytest.approx(10)
    assert result.projected_drawdown_pct == pytest.approx(0.1)

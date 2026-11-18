
import pytest
from pydantic import ValidationError

from app.portfolio.risk_manager import (
    OpenPositionRisk,
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


@pytest.fixture
def normal_snapshot():
    return PortfolioSnapshot(
        current_equity=10000,
        day_start_equity=10000,
        peak_equity=10000,
        daily_realized_loss=0,
        open_positions=[
            OpenPositionRisk(
                ticket="1001",
                symbol="EURUSD",
                risk_to_stop=10,
            )
        ],
    )


def test_approves_trade_within_portfolio_limits(
    normal_snapshot,
    risk_config,
):
    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=normal_snapshot,
        proposed_trade_risk=10,
        risk_config=risk_config,
    )

    assert result.approved is True
    assert result.open_position_count == 1
    assert result.existing_open_risk == pytest.approx(10)
    assert result.proposed_trade_risk == pytest.approx(10)
    assert result.projected_total_open_risk == pytest.approx(20)
    assert result.daily_loss_limit == pytest.approx(100)


def test_rejects_trade_when_combined_risk_exceeds_daily_limit(
    risk_config,
):
    snapshot = PortfolioSnapshot(
        current_equity=10000,
        day_start_equity=10000,
        peak_equity=10000,
        daily_realized_loss=0,
        open_positions=[
            OpenPositionRisk(
                ticket="1001",
                symbol="EURUSD",
                risk_to_stop=85,
            )
        ],
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=20,
        risk_config=risk_config,
    )

    assert result.approved is False
    assert result.projected_total_open_risk == pytest.approx(105)
    assert any(
        "daily loss limit" in reason.lower()
        for reason in result.reasons
    )


def test_rejects_trade_when_maximum_positions_reached(
    risk_config,
):
    snapshot = PortfolioSnapshot(
        current_equity=10000,
        day_start_equity=10000,
        peak_equity=10000,
        daily_realized_loss=0,
        open_positions=[
            OpenPositionRisk(
                ticket="1001",
                symbol="EURUSD",
                risk_to_stop=10,
            ),
            OpenPositionRisk(
                ticket="1002",
                symbol="GBPUSD",
                risk_to_stop=10,
            ),
        ],
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=10,
        risk_config=risk_config,
    )

    assert result.approved is False
    assert any(
        "position limit" in reason.lower()
        for reason in result.reasons
    )


def test_rejects_trade_when_daily_loss_limit_already_reached(
    risk_config,
):
    snapshot = PortfolioSnapshot(
        current_equity=9900,
        day_start_equity=10000,
        peak_equity=10000,
        daily_realized_loss=100,
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=1,
        risk_config=risk_config,
    )

    assert result.approved is False
    assert any(
        "already been reached" in reason.lower()
        for reason in result.reasons
    )


def test_rejects_trade_when_drawdown_limit_reached(
    risk_config,
):
    snapshot = PortfolioSnapshot(
        current_equity=9400,
        day_start_equity=10000,
        peak_equity=10000,
        daily_realized_loss=0,
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=10,
        risk_config=risk_config,
    )

    assert result.approved is False
    assert result.current_drawdown_pct == pytest.approx(6.0)
    assert any(
        "drawdown limit" in reason.lower()
        for reason in result.reasons
    )


def test_rejects_trade_when_emergency_halt_is_active(
    normal_snapshot,
    risk_config,
):
    snapshot = normal_snapshot.model_copy(
        update={"emergency_halt": True}
    )

    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=10,
        risk_config=risk_config,
    )

    assert result.approved is False
    assert result.emergency_halt is True
    assert any(
        "emergency" in reason.lower()
        for reason in result.reasons
    )


def test_rejects_trade_exceeding_individual_risk_limit(
    normal_snapshot,
    risk_config,
):
    result = PortfolioRiskManager.evaluate_new_trade(
        snapshot=normal_snapshot,
        proposed_trade_risk=30,
        risk_config=risk_config,
    )

    assert result.approved is False
    assert any(
        "per-trade risk limit" in reason.lower()
        for reason in result.reasons
    )


def test_rejects_duplicate_position_tickets():
    with pytest.raises(ValidationError, match="unique"):
        PortfolioSnapshot(
            current_equity=10000,
            day_start_equity=10000,
            peak_equity=10000,
            daily_realized_loss=0,
            open_positions=[
                OpenPositionRisk(
                    ticket="1001",
                    symbol="EURUSD",
                    risk_to_stop=10,
                ),
                OpenPositionRisk(
                    ticket="1001",
                    symbol="GBPUSD",
                    risk_to_stop=15,
                ),
            ],
        )


def test_rejects_non_finite_proposed_trade_risk(
    normal_snapshot,
    risk_config,
):
    with pytest.raises(ValueError, match="finite"):
        PortfolioRiskManager.evaluate_new_trade(
            snapshot=normal_snapshot,
            proposed_trade_risk=float("inf"),
            risk_config=risk_config,
        )

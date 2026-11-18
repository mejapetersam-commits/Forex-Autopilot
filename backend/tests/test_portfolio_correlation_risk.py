import pytest

from app.portfolio.correlation import CorrelationResult
from app.portfolio.risk_manager import (
    OpenPositionRisk,
    PortfolioRiskManager,
    PortfolioSnapshot,
)
from app.risk.risk_config import RiskConfig


@pytest.fixture
def risk_config():
    return RiskConfig(
        risk_per_trade_pct=0.5,
        max_daily_loss_pct=1.0,
        max_drawdown_pct=5.0,
        max_open_positions=3,
        correlation_check_enabled=True,
        correlation_threshold=0.80,
        max_correlated_group_risk_pct=0.50,
    )


@pytest.fixture
def snapshot():
    return PortfolioSnapshot(
        current_equity=10000.0,
        day_start_equity=10000.0,
        peak_equity=10000.0,
        daily_realized_loss=0.0,
        open_positions=[
            OpenPositionRisk(
                ticket="1001",
                symbol="EURUSD",
                risk_to_stop=30.0,
            )
        ],
    )


def correlation(symbol_a="EURUSD", symbol_b="GBPUSD", coefficient=0.90):
    return CorrelationResult(
        symbol_a=symbol_a,
        symbol_b=symbol_b,
        coefficient=coefficient,
        observations=100,
    )


def evaluate(snapshot, risk_config, correlations):
    return PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=25.0,
        risk_config=risk_config,
        proposed_symbol="GBPUSD",
        correlation_results=correlations,
    )


def test_rejects_trade_when_strong_positive_correlation_exceeds_group_risk(
    snapshot,
    risk_config,
):
    decision = evaluate(
        snapshot,
        risk_config,
        [correlation(coefficient=0.90)],
    )

    assert decision.approved is False
    assert decision.correlated_open_risk == pytest.approx(30.0)
    assert decision.projected_correlated_group_risk == pytest.approx(55.0)
    assert decision.max_correlated_group_risk == pytest.approx(50.0)
    assert decision.strongest_correlation == pytest.approx(0.90)
    assert any("correlated-position group risk" in reason for reason in decision.reasons)


def test_rejects_trade_when_strong_negative_correlation_exceeds_group_risk(
    snapshot,
    risk_config,
):
    decision = evaluate(
        snapshot,
        risk_config,
        [correlation(coefficient=-0.95)],
    )

    assert decision.approved is False
    assert decision.strongest_correlation == pytest.approx(-0.95)
    assert any("correlated-position group risk" in reason for reason in decision.reasons)


def test_allows_trade_when_correlation_is_below_threshold(
    snapshot,
    risk_config,
):
    decision = evaluate(
        snapshot,
        risk_config,
        [correlation(coefficient=0.35)],
    )

    assert decision.approved is True
    assert decision.correlated_open_risk == pytest.approx(0.0)
    assert decision.projected_correlated_group_risk == pytest.approx(25.0)
    assert decision.strongest_correlation == pytest.approx(0.35)


def test_fails_closed_when_correlation_data_is_missing(
    snapshot,
    risk_config,
):
    decision = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=25.0,
        risk_config=risk_config,
        proposed_symbol="GBPUSD",
    )

    assert decision.approved is False
    assert any("Correlation data is missing" in reason for reason in decision.reasons)


def test_fails_closed_when_pair_correlation_is_missing(
    snapshot,
    risk_config,
):
    decision = evaluate(snapshot, risk_config, [])

    assert decision.approved is False
    assert any("Correlation data is missing for GBPUSD and EURUSD" in reason
               for reason in decision.reasons)


def test_fails_closed_when_proposed_symbol_is_missing(
    snapshot,
    risk_config,
):
    decision = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=25.0,
        risk_config=risk_config,
        correlation_results=[correlation()],
    )

    assert decision.approved is False
    assert any("proposed instrument symbol" in reason for reason in decision.reasons)


def test_correlation_check_does_not_require_data_when_no_positions_are_open(
    risk_config,
):
    empty_snapshot = PortfolioSnapshot(
        current_equity=10000.0,
        day_start_equity=10000.0,
        peak_equity=10000.0,
        daily_realized_loss=0.0,
    )

    decision = PortfolioRiskManager.evaluate_new_trade(
        snapshot=empty_snapshot,
        proposed_trade_risk=25.0,
        risk_config=risk_config,
        proposed_symbol="GBPUSD",
    )

    assert decision.approved is True
    assert decision.correlated_open_risk == pytest.approx(0.0)


def test_duplicate_pair_measurements_reject_trade(
    snapshot,
    risk_config,
):
    decision = evaluate(
        snapshot,
        risk_config,
        [
            correlation(coefficient=0.90),
            correlation(coefficient=0.91),
        ],
    )

    assert decision.approved is False
    assert any("Duplicate correlation data" in reason for reason in decision.reasons)

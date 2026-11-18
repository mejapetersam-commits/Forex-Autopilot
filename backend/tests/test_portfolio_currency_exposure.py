
import pytest

from app.portfolio.currency_exposure import CurrencyExposure
from app.portfolio.risk_manager import (
    OpenPositionRisk,
    PortfolioRiskManager,
    PortfolioSnapshot,
)
from app.risk.risk_config import RiskConfig


@pytest.fixture
def risk_config():
    return RiskConfig(
        risk_per_trade_pct=0.25,
        max_daily_loss_pct=1.0,
        max_drawdown_pct=5.0,
        max_currency_exposure_pct=200.0,
        max_open_positions=3,
    )


@pytest.fixture
def empty_snapshot():
    return PortfolioSnapshot(
        current_equity=10000.0,
        day_start_equity=10000.0,
        peak_equity=10000.0,
        daily_realized_loss=0.0,
        daily_floating_pnl=0.0,
        open_positions=[],
    )


def exposure(ticket, currency, amount):
    return CurrencyExposure(
        ticket=ticket,
        currency=currency,
        amount_account_currency=amount,
    )


def test_trade_approved_within_currency_exposure_limit(
    empty_snapshot,
    risk_config,
):
    existing_position = OpenPositionRisk(
        ticket="1001",
        symbol="EURUSD",
        risk_to_stop=10.0,
        currency_exposures=[
            exposure("1001", "EUR", 10000.0),
        ],
    )

    snapshot = empty_snapshot.model_copy(
        update={"open_positions": [existing_position]}
    )

    decision = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=10.0,
        risk_config=risk_config,
        proposed_currency_exposures=[
            exposure("1002", "EUR", 5000.0),
        ],
    )

    assert decision.approved is True
    assert decision.projected_currency_exposure_pct["EUR"] == 150.0


def test_trade_rejected_when_currency_exposure_exceeds_limit(
    empty_snapshot,
    risk_config,
):
    existing_position = OpenPositionRisk(
        ticket="1001",
        symbol="EURUSD",
        risk_to_stop=10.0,
        currency_exposures=[
            exposure("1001", "EUR", 15000.0),
        ],
    )

    snapshot = empty_snapshot.model_copy(
        update={"open_positions": [existing_position]}
    )

    decision = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=10.0,
        risk_config=risk_config,
        proposed_currency_exposures=[
            exposure("1002", "EUR", 10000.0),
        ],
    )

    assert decision.approved is False
    assert decision.projected_currency_exposure_pct["EUR"] == 250.0
    assert any(
        "gross EUR exposure" in reason
        for reason in decision.reasons
    )


def test_exposure_from_multiple_open_positions_is_combined(
    empty_snapshot,
    risk_config,
):
    position_one = OpenPositionRisk(
        ticket="1001",
        symbol="EURUSD",
        risk_to_stop=5.0,
        currency_exposures=[
            exposure("1001", "EUR", 8000.0),
        ],
    )

    position_two = OpenPositionRisk(
        ticket="1002",
        symbol="EURGBP",
        risk_to_stop=5.0,
        currency_exposures=[
            exposure("1002", "EUR", 7000.0),
        ],
    )

    snapshot = empty_snapshot.model_copy(
        update={
            "open_positions": [
                position_one,
                position_two,
            ]
        }
    )

    decision = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=5.0,
        risk_config=risk_config,
        proposed_currency_exposures=[
            exposure("1003", "EUR", 6000.0),
        ],
    )

    assert decision.approved is False
    assert decision.projected_currency_exposure_pct["EUR"] == 210.0


def test_opposing_positions_do_not_hide_gross_exposure(
    empty_snapshot,
    risk_config,
):
    existing_position = OpenPositionRisk(
        ticket="1001",
        symbol="EURUSD",
        risk_to_stop=10.0,
        currency_exposures=[
            exposure("1001", "EUR", 15000.0),
        ],
    )

    snapshot = empty_snapshot.model_copy(
        update={"open_positions": [existing_position]}
    )

    decision = PortfolioRiskManager.evaluate_new_trade(
        snapshot=snapshot,
        proposed_trade_risk=10.0,
        risk_config=risk_config,
        proposed_currency_exposures=[
            exposure("1002", "EUR", -10000.0),
        ],
    )

    assert decision.approved is False
    assert decision.projected_currency_exposure_pct["EUR"] == 250.0


def test_currency_exposure_is_optional_for_legacy_callers(
    empty_snapshot,
    risk_config,
):
    decision = PortfolioRiskManager.evaluate_new_trade(
        snapshot=empty_snapshot,
        proposed_trade_risk=10.0,
        risk_config=risk_config,
    )

    assert decision.approved is True
    assert decision.projected_currency_exposure_pct == {}

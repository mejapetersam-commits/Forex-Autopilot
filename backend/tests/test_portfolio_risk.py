from app.execution.portfolio_risk import evaluate_portfolio_risk


def healthy_portfolio():
    return {"status": "healthy", "open_position_count": 1,
            "account_equity": 10000.0, "total_open_stop_risk": 25.0}


def test_portfolio_risk_gate_approves_known_risk_below_cap():
    result = evaluate_portfolio_risk(healthy_portfolio(), max_stop_risk_pct=0.5)
    assert result["approved"] is True
    assert result["aggregate_stop_risk_pct"] == 0.25
    assert result["execution_submitted"] is False


def test_portfolio_risk_gate_blocks_risk_above_cap():
    result = evaluate_portfolio_risk(healthy_portfolio(), max_stop_risk_pct=0.2)
    assert result["approved"] is False
    assert any("exceeds" in reason for reason in result["reasons"])


def test_portfolio_risk_gate_blocks_incomplete_unknown_stop_risk():
    portfolio = healthy_portfolio()
    portfolio.update(status="incomplete", total_open_stop_risk=None)
    result = evaluate_portfolio_risk(portfolio)
    assert result["approved"] is False
    assert len(result["reasons"]) >= 2


def test_portfolio_risk_gate_blocks_stale_and_invalid_equity():
    portfolio = healthy_portfolio()
    portfolio.update(status="stale", account_equity=0)
    assert evaluate_portfolio_risk(portfolio)["approved"] is False


def test_portfolio_risk_gate_rejects_invalid_limit_and_non_finite_values():
    assert not evaluate_portfolio_risk(healthy_portfolio(), max_stop_risk_pct=float("nan"))["approved"]
    portfolio = healthy_portfolio()
    portfolio["total_open_stop_risk"] = float("inf")
    assert not evaluate_portfolio_risk(portfolio)["approved"]

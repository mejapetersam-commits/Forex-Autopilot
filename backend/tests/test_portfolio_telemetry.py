from datetime import datetime, timedelta, timezone
from app.portfolio.telemetry import build_portfolio_exposure

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)

def fixtures():
    stamp = NOW.isoformat()
    state = {"environment":"demo","observed_at":stamp,"positions":[
        {"ticket":"1001","symbol":"EURUSDM","side":"buy","volume_lots":0.01,"stop_loss":1.09}
    ]}
    account = {"equity":10000.0,"account_currency":"USD","observed_at":stamp}
    quotes = [{"symbol":"EURUSDM","bid":1.10,"ask":1.1002,"observed_at":stamp}]
    specs = [{"symbol":"EURUSDM","base_currency":"EUR","profit_currency":"USD",
              "contract_size":100000.0,"tick_size":0.00001,"tick_value_loss":1.0,
              "observed_at":stamp}]
    return state, account, quotes, specs

def test_portfolio_exposure_converts_base_and_quote_currency_and_stop_risk():
    state, account, quotes, specs = fixtures()
    result = build_portfolio_exposure(execution_state=state, account=account,
                                      quotes=quotes, specifications=specs, now=NOW)
    assert result["status"] == "healthy"
    assert result["open_position_count"] == 1
    by_currency = {row["currency"]: row for row in result["currencies"]}
    assert round(by_currency["EUR"]["net_exposure"], 2) == 1100.10
    assert round(by_currency["USD"]["net_exposure"], 2) == -1100.10
    assert result["total_open_stop_risk"] == 100.0
    assert result["trading_enabled"] is False

def test_portfolio_marks_missing_stop_as_incomplete_and_unknown_risk():
    state, account, quotes, specs = fixtures()
    state["positions"][0]["stop_loss"] = 0
    result = build_portfolio_exposure(execution_state=state, account=account,
                                      quotes=quotes, specifications=specs, now=NOW)
    assert result["status"] == "incomplete"
    assert result["total_open_stop_risk"] is None
    assert any("no protective stop" in reason for reason in result["reasons"])

def test_portfolio_fails_closed_on_stale_account_or_execution_state():
    state, account, quotes, specs = fixtures()
    account["observed_at"] = (NOW - timedelta(seconds=31)).isoformat()
    result = build_portfolio_exposure(execution_state=state, account=account,
                                      quotes=quotes, specifications=specs, now=NOW)
    assert result["status"] == "stale"
    assert result["positions"] == []
    assert result["currencies"] == []

from app.strategy.registry import evaluate_registered_strategy, list_strategies


def test_registry_lists_stable_research_strategy():
    strategies = list_strategies()
    assert strategies
    assert strategies[0]["strategy_id"] == "sma_rsi_momentum"


def test_registry_rejects_unknown_strategy():
    try:
        evaluate_registered_strategy("not-a-strategy", [])
    except ValueError as exc:
        assert "Unknown strategy_id" in str(exc)
    else:
        raise AssertionError("Unknown strategy identifier should fail.")

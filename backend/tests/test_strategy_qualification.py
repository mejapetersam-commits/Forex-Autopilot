from app.backtesting.qualification import evaluate_strategy_qualification


def valid_walk_forward():
    return {
        "status": "completed",
        "folds": [
            {"out_of_sample_metrics": {"status": "completed", "total_trades": 12}},
            {"out_of_sample_metrics": {"status": "completed", "total_trades": 12}},
        ],
        "out_of_sample_summary": {
            "valid_folds": 2, "total_trades": 24,
            "mean_return_pct": 2.1, "mean_profit_factor": 1.45,
            "worst_drawdown_pct": 3.2,
        },
    }


def test_qualification_marks_strong_oos_evidence_eligible_for_demo_observation():
    result = evaluate_strategy_qualification(valid_walk_forward(), {"status": "healthy", "issue_count": 0})
    assert result["status"] == "eligible_for_demo_observation"
    assert result["eligible_for_demo_observation"] is True
    assert result["trading_enabled"] is False
    assert result["execution_enabled"] is False


def test_qualification_rejects_small_oos_sample():
    wf = valid_walk_forward()
    wf["out_of_sample_summary"]["total_trades"] = 8
    result = evaluate_strategy_qualification(wf, {"status": "healthy", "issue_count": 0})
    assert result["status"] == "insufficient_evidence"
    assert any("out-of-sample trades" in reason for reason in result["reasons"])


def test_qualification_flags_weak_performance_or_data_quality():
    wf = valid_walk_forward()
    wf["out_of_sample_summary"]["mean_profit_factor"] = 1.05
    result = evaluate_strategy_qualification(wf, {"status": "degraded", "issue_count": 2})
    assert result["status"] == "under_review"
    assert result["eligible_for_demo_observation"] is False
    assert len(result["reasons"]) >= 2


def test_qualification_requires_both_valid_folds():
    wf = valid_walk_forward()
    wf["folds"][1]["out_of_sample_metrics"]["status"] = "insufficient_data"
    result = evaluate_strategy_qualification(wf, {"status": "healthy", "issue_count": 0})
    assert result["status"] == "insufficient_evidence"



def test_qualification_blocks_insufficient_history_even_with_strong_backtest_metrics():
    quality = {"status": "healthy", "issue_count": 0, "ready_for_research": False}
    result = evaluate_strategy_qualification(valid_walk_forward(), quality)
    assert result["status"] == "under_review"
    assert result["eligible_for_demo_observation"] is False
    assert any("coverage" in reason for reason in result["reasons"])

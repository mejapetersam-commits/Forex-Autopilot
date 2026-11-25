from app.backtesting.qualification import evaluate_strategy_qualification


def valid_walk_forward():
    fold_metrics = [
        {
            "status": "completed",
            "total_trades": 12,
            "return_pct": 1.8,
            "profit_factor": 1.45,
            "max_drawdown_pct": 3.2,
            "mark_to_market_max_drawdown_pct": 3.8,
            "qualification_drawdown_pct": 3.8,
            "expectancy_per_trade": 7.5,
        },
        {
            "status": "completed",
            "total_trades": 12,
            "return_pct": 2.4,
            "profit_factor": 1.45,
            "max_drawdown_pct": 2.8,
            "mark_to_market_max_drawdown_pct": 3.1,
            "qualification_drawdown_pct": 3.1,
            "expectancy_per_trade": 8.0,
        },
    ]
    return {
        "status": "completed",
        "folds": [
            {"out_of_sample_metrics": item} for item in fold_metrics
        ],
        "out_of_sample_summary": {
            "valid_folds": 2,
            "total_trades": 24,
            "mean_return_pct": 2.1,
            "mean_profit_factor": 1.45,
            "worst_drawdown_pct": 3.2,
            "worst_qualification_drawdown_pct": 3.8,
        },
    }


def healthy_quality():
    return {"status": "healthy", "issue_count": 0}


def test_strong_oos_evidence_is_eligible_for_demo_observation():
    result = evaluate_strategy_qualification(valid_walk_forward(), healthy_quality())
    assert result["status"] == "eligible_for_demo_observation"
    assert result["eligible_for_demo_observation"] is True
    assert result["trading_enabled"] is False
    assert result["execution_enabled"] is False


def test_rejects_small_oos_sample():
    wf = valid_walk_forward()
    wf["folds"][0]["out_of_sample_metrics"]["total_trades"] = 4
    wf["folds"][1]["out_of_sample_metrics"]["total_trades"] = 4
    result = evaluate_strategy_qualification(wf, healthy_quality())
    assert result["status"] == "insufficient_evidence"


def test_rejects_a_losing_fold_even_when_summary_is_positive():
    wf = valid_walk_forward()
    wf["folds"][0]["out_of_sample_metrics"]["return_pct"] = -1.0
    result = evaluate_strategy_qualification(wf, healthy_quality())
    assert result["status"] == "under_review"
    assert not result["eligible_for_demo_observation"]
    assert any("fold 1 failed" in reason for reason in result["reasons"])


def test_rejects_weak_profit_factor_in_one_fold():
    wf = valid_walk_forward()
    wf["folds"][1]["out_of_sample_metrics"]["profit_factor"] = 1.05
    result = evaluate_strategy_qualification(wf, healthy_quality())
    assert result["status"] == "under_review"
    assert any("fold 2 failed" in reason for reason in result["reasons"])


def test_rejects_excessive_drawdown_in_one_fold():
    wf = valid_walk_forward()
    wf["folds"][0]["out_of_sample_metrics"]["max_drawdown_pct"] = 6.0
    result = evaluate_strategy_qualification(wf, healthy_quality())
    assert result["status"] == "under_review"


def test_rejects_missing_or_non_finite_fold_metrics():
    wf = valid_walk_forward()
    wf["folds"][0]["out_of_sample_metrics"]["expectancy_per_trade"] = None
    wf["folds"][1]["out_of_sample_metrics"]["profit_factor"] = float("inf")
    result = evaluate_strategy_qualification(wf, healthy_quality())
    assert result["status"] == "under_review"
    assert not result["eligible_for_demo_observation"]


def test_requires_both_valid_folds():
    wf = valid_walk_forward()
    wf["folds"][1]["out_of_sample_metrics"]["status"] = "insufficient_data"
    result = evaluate_strategy_qualification(wf, healthy_quality())
    assert result["status"] == "insufficient_evidence"


def test_blocks_degraded_data_quality():
    result = evaluate_strategy_qualification(
        valid_walk_forward(),
        {"status": "degraded", "issue_count": 2},
    )
    assert result["status"] == "under_review"
    assert not result["eligible_for_demo_observation"]


def test_blocks_insufficient_history():
    result = evaluate_strategy_qualification(
        valid_walk_forward(),
        {"status": "healthy", "issue_count": 0, "ready_for_research": False},
    )
    assert result["status"] == "under_review"
    assert any("coverage" in reason for reason in result["reasons"])


def test_rejects_excessive_mark_to_market_drawdown():
    wf = valid_walk_forward()
    wf["folds"][0]["out_of_sample_metrics"]["mark_to_market_max_drawdown_pct"] = 6.0
    wf["folds"][0]["out_of_sample_metrics"]["qualification_drawdown_pct"] = 6.0
    wf["out_of_sample_summary"]["worst_qualification_drawdown_pct"] = 6.0
    result = evaluate_strategy_qualification(wf, healthy_quality())
    assert result["status"] == "under_review"
    assert not result["eligible_for_demo_observation"]
    assert any("mark-to-market drawdown" in reason for reason in result["reasons"])


def test_rejects_missing_conservative_drawdown_metric():
    wf = valid_walk_forward()
    del wf["folds"][0]["out_of_sample_metrics"]["qualification_drawdown_pct"]
    result = evaluate_strategy_qualification(wf, healthy_quality())
    assert result["status"] == "under_review"
    assert not result["eligible_for_demo_observation"]

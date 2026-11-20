import hashlib

from app.execution.position_reconciliation import reconcile_open_positions


def test_position_with_known_intent_tag_is_matched():
    intent = {"idempotency_key": "intent-123"}
    tag = hashlib.sha256(b"intent-123").hexdigest()[:12]
    result = reconcile_open_positions(
        [{"ticket": "10", "position_id": "20", "symbol": "EURUSDm",
          "side": "buy", "volume_lots": 0.01, "magic": 61119001,
          "comment": "FA:" + tag}],
        [intent], expected_magic=61119001,
    )
    assert result["status"] == "complete"
    assert result["managed_positions_checked"] == 1
    assert result["orphaned_positions"] == []


def test_unmatched_managed_position_is_flagged_not_modified():
    result = reconcile_open_positions(
        [{"ticket": "10", "position_id": "20", "symbol": "EURUSDm",
          "side": "buy", "volume_lots": 0.01, "magic": 61119001,
          "comment": "manual trade"}],
        [], expected_magic=61119001,
    )
    assert result["status"] == "review_required"
    assert result["orphaned_positions"][0]["reason"] == "managed_position_without_matching_intent_tag"
    assert result["trading_enabled"] is False


def test_positions_with_other_magic_are_ignored():
    result = reconcile_open_positions(
        [{"ticket": "10", "position_id": "20", "symbol": "EURUSDm",
          "side": "buy", "volume_lots": 0.01, "magic": 123,
          "comment": ""}],
        [], expected_magic=61119001,
    )
    assert result["managed_positions_checked"] == 0
    assert result["status"] == "complete"

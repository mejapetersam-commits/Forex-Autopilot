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


def _intent(key="intent-identity", symbol="EURUSDm", side="buy"):
    return {
        "idempotency_key": key,
        "payload": {"symbol": symbol, "side": side, "volume_lots": 0.01},
    }


def test_matching_tag_still_flags_symbol_or_side_mismatch():
    import hashlib
    key = "intent-identity"
    tag = hashlib.sha256(key.encode()).hexdigest()[:12]
    result = reconcile_open_positions(
        [{"ticket": "20", "position_id": "30", "symbol": "GBPUSDm",
          "side": "sell", "volume_lots": 0.01, "magic": 61119001,
          "comment": "FA:" + tag}],
        [_intent(key)], expected_magic=61119001,
    )
    assert result["status"] == "review_required"
    assert set(result["mismatched_positions"][0]["reasons"]) == {
        "broker_position_symbol_mismatch", "broker_position_side_mismatch"
    }


def test_duplicate_position_identity_requires_review():
    import hashlib
    key = "intent-duplicate"
    tag = hashlib.sha256(key.encode()).hexdigest()[:12]
    positions = [
        {"ticket": ticket, "position_id": "shared-position", "symbol": "EURUSDm",
         "side": "buy", "volume_lots": 0.01, "magic": 61119001,
         "comment": "FA:" + tag}
        for ticket in ("40", "41")
    ]
    result = reconcile_open_positions(
        positions, [_intent(key)], expected_magic=61119001,
    )
    assert result["status"] == "review_required"
    assert result["duplicate_position_identities"] == [{
        "position_identity": "shared-position", "tickets": ["40", "41"]
    }]


def test_partial_close_volume_is_not_mistaken_for_identity_mismatch():
    import hashlib
    key = "intent-partial-close"
    tag = hashlib.sha256(key.encode()).hexdigest()[:12]
    result = reconcile_open_positions(
        [{"ticket": "50", "position_id": "60", "symbol": "EURUSDm",
          "side": "buy", "volume_lots": 0.004, "magic": 61119001,
          "comment": "FA:" + tag}],
        [_intent(key)], expected_magic=61119001,
    )
    assert result["status"] == "complete"
    assert result["mismatched_positions"] == []
    assert result["read_only"] is True

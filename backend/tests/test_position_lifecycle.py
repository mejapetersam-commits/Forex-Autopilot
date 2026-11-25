from app.execution.position_lifecycle import compare_position_lifecycle


def snapshot(at, positions, terminal="terminal-001", server="Exness-MT5Trial"):
    return {
        "terminal_id": terminal, "server": server, "environment": "demo",
        "observed_at": at, "positions": positions,
    }


def position(ticket="100", position_id="900", volume=0.02, sl=1.08, tp=1.12, magic=61119001):
    return {
        "ticket": ticket, "position_id": position_id, "symbol": "EURUSDM",
        "side": "buy", "volume_lots": volume, "stop_loss": sl,
        "take_profit": tp, "magic": magic,
    }


def test_detects_partial_close_protection_change_and_ticket_replacement():
    previous = snapshot("2026-11-19T10:00:00+00:00", [position()])
    current = snapshot("2026-11-19T10:00:05+00:00", [
        position(ticket="101", volume=0.01, sl=1.09, tp=1.12)
    ])
    result = compare_position_lifecycle(previous, current, expected_magic=61119001)
    kinds = [event["event_type"] for event in result["events"]]
    assert result["status"] == "complete"
    assert "position_ticket_replaced" in kinds
    assert "position_partially_closed_observed" in kinds
    assert "position_protection_changed" in kinds


def test_absent_position_is_not_called_closed_without_deal_evidence():
    previous = snapshot("2026-11-19T10:00:00+00:00", [position()])
    current = snapshot("2026-11-19T10:00:05+00:00", [])
    result = compare_position_lifecycle(previous, current, expected_magic=61119001)
    assert result["events"][0]["event_type"] == "position_disappearance_unconfirmed"
    assert result["events"][0]["close_confirmed_by_deals"] is False


def test_full_close_requires_deal_volume_evidence():
    previous = snapshot("2026-11-19T10:00:00+00:00", [position(volume=0.02)])
    current = snapshot("2026-11-19T10:00:05+00:00", [])
    deals = {"900": [
        {"entry": "in", "volume_lots": 0.02},
        {"entry": "out", "volume_lots": 0.02},
    ]}
    result = compare_position_lifecycle(
        previous, current, deals_by_position=deals, expected_magic=61119001
    )
    assert result["events"][0]["event_type"] == "position_closed_confirmed"


def test_reversal_deal_makes_close_evidence_ambiguous():
    previous = snapshot("2026-11-19T10:00:00+00:00", [position()])
    current = snapshot("2026-11-19T10:00:05+00:00", [])
    deals = {"900": [
        {"entry": "in", "volume_lots": 0.02},
        {"entry": "inout", "volume_lots": 0.02},
    ]}
    result = compare_position_lifecycle(
        previous, current, deals_by_position=deals, expected_magic=61119001
    )
    assert result["events"][0]["event_type"] == "position_disappearance_unconfirmed"
    assert result["events"][0]["ambiguous_reversal_deal"] is True


def test_different_terminal_cannot_be_compared_as_same_lifecycle():
    previous = snapshot("2026-11-19T10:00:00+00:00", [position()])
    current = snapshot("2026-11-19T10:00:05+00:00", [], terminal="terminal-002")
    result = compare_position_lifecycle(previous, current, expected_magic=61119001)
    assert result["status"] == "baseline_only"
    assert result["events"] == []


def test_ignores_positions_with_other_magic_numbers():
    previous = snapshot("2026-11-19T10:00:00+00:00", [position(magic=123)])
    current = snapshot("2026-11-19T10:00:05+00:00", [position(magic=123)])
    result = compare_position_lifecycle(previous, current, expected_magic=61119001)
    assert result["managed_positions_current"] == 0
    assert result["events"] == []

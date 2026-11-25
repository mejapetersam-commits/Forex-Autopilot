from app.execution.ledger import ExecutionLedger


def test_list_intents_returns_decoded_payloads_for_reconciliation(tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "ledger.sqlite3"))
    ledger.create_intent(
        "intent-123",
        {"symbol": "EURUSDm", "side": "buy", "volume_lots": 0.01},
    )
    rows = ledger.list_intents()
    assert len(rows) == 1
    assert rows[0]["idempotency_key"] == "intent-123"
    assert rows[0]["payload"]["symbol"] == "EURUSDm"

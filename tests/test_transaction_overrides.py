import json
from unittest.mock import MagicMock, patch

import pytest

from transaction_overrides import (
    load_budget,
    load_provisional_attempts,
    load_store,
    record_provisional_attempt,
    record_provisional_transaction,
    record_reprint,
    set_budget,
    set_decision,
)


def test_set_decision_persists_and_auto_removes(tmp_path):
    path = str(tmp_path / "overrides.json")

    set_decision("tx-1", "exclude", path)
    assert load_store(path)["transactions"]["tx-1"]["decision"] == "exclude"

    set_decision("tx-1", "auto", path)
    assert "tx-1" not in load_store(path)["transactions"]


def test_record_reprint_increments_count(tmp_path):
    path = str(tmp_path / "overrides.json")

    first = record_reprint({"bytes": 53856}, path)
    second = record_reprint({"bytes": 53856}, path)

    assert first["count"] == 1
    assert second["count"] == 2
    assert load_store(path)["reprint"]["metadata"]["bytes"] == 53856


def test_record_provisional_transaction_normalizes_payload(tmp_path):
    path = str(tmp_path / "overrides.json")

    transaction = record_provisional_transaction(
        {
            "source": "apple_wallet",
            "merchant": "Target",
            "amount": "$42.19",
            "card": "Apple Card",
            "occurred_at": "2026-08-27T17:12:00-05:00",
        },
        path,
    )

    store = load_store(path)
    assert transaction["id"].startswith("prov-")
    assert transaction["amount_milliunits"] == 42190
    assert transaction["status"] == "pending"
    assert transaction["seen_count"] == 1
    assert store["provisional_transactions"][transaction["id"]]["merchant"] == "Target"


def test_record_provisional_transaction_is_idempotent_for_same_payload(tmp_path):
    path = str(tmp_path / "overrides.json")
    payload = {
        "source": "apple_wallet",
        "merchant": "Coffee Shop",
        "amount": "7.50",
        "occurred_at": "2026-08-27T17:12:00-05:00",
    }

    first = record_provisional_transaction(payload, path)
    second = record_provisional_transaction(payload, path)

    assert second["id"] == first["id"]
    assert second["seen_count"] == 2
    assert len(load_store(path)["provisional_transactions"]) == 1


def test_record_provisional_transaction_rejects_missing_amount(tmp_path):
    with pytest.raises(ValueError, match="amount is required"):
        record_provisional_transaction({"merchant": "Target"}, str(tmp_path / "overrides.json"))


def test_record_provisional_attempt_appends_attempts(tmp_path):
    path = str(tmp_path / "overrides.json")

    first = record_provisional_attempt({"merchant": "Target"}, "rejected", error="amount is required", path=path)
    second = record_provisional_attempt(
        {"merchant": "Coffee", "amount": "4.50"},
        "accepted",
        transaction_id="prov-123",
        path=path,
    )

    attempts = load_provisional_attempts(path)
    assert first["status"] == "rejected"
    assert first["error"] == "amount is required"
    assert second["transaction_id"] == "prov-123"
    assert [attempt["status"] for attempt in attempts] == ["rejected", "accepted"]


def test_record_provisional_attempt_keeps_recent_attempts(tmp_path):
    path = str(tmp_path / "overrides.json")

    with patch("transaction_overrides.PROVISIONAL_ATTEMPT_LIMIT", 2):
        record_provisional_attempt({"attempt": 1}, "rejected", path=path)
        record_provisional_attempt({"attempt": 2}, "rejected", path=path)
        record_provisional_attempt({"attempt": 3}, "rejected", path=path)

    attempts = load_provisional_attempts(path)
    assert [attempt["payload"]["attempt"] for attempt in attempts] == [2, 3]


def test_remote_store_uses_upstash_rest_env():
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {
            "result": json.dumps(
                {
                    "version": 1,
                    "transactions": {"tx-1": {"decision": "exclude"}},
                    "provisional_attempts": [{"status": "accepted"}],
                    "reprint": {},
                }
            )
        }
    ).encode("utf-8")

    with patch.dict(
        "os.environ",
        {
            "UPSTASH_REDIS_REST_URL": "https://redis.example.com",
            "UPSTASH_REDIS_REST_TOKEN": "token",
        },
    ), patch("transaction_overrides.urlopen", return_value=response) as mock_urlopen:
        store = load_store()

    assert store["transactions"]["tx-1"]["decision"] == "exclude"
    assert store["provisional_transactions"] == {}
    assert store["provisional_attempts"] == [{"status": "accepted"}]
    request = mock_urlopen.call_args[0][0]
    assert request.full_url == "https://redis.example.com"
    assert request.headers["Authorization"] == "Bearer token"


def test_budget_defaults_to_none_when_unset(tmp_path):
    path = str(tmp_path / "overrides.json")

    assert load_budget(path) is None


def test_set_budget_persists_monthly_amount(tmp_path):
    path = str(tmp_path / "overrides.json")

    budget = set_budget(2000, path)

    assert budget["monthly"] == 2000.0
    assert budget["updated_at"]
    assert load_budget(path) == 2000.0
    assert load_store(path)["budget"]["monthly"] == 2000.0


def test_set_budget_accepts_formatted_text(tmp_path):
    path = str(tmp_path / "overrides.json")

    assert set_budget("$2,000.50", path)["monthly"] == 2000.5
    assert load_budget(path) == 2000.5


def test_set_budget_allows_zero_to_fall_back_to_ynab(tmp_path):
    path = str(tmp_path / "overrides.json")

    set_budget(0, path)

    assert load_budget(path) == 0.0


@pytest.mark.parametrize("value", ["", None, "abc", -5, "-12.50"])
def test_set_budget_rejects_invalid_amounts(tmp_path, value):
    path = str(tmp_path / "overrides.json")

    with pytest.raises(ValueError):
        set_budget(value, path)

    assert load_budget(path) is None

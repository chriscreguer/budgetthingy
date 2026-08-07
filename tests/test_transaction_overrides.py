import json
from unittest.mock import MagicMock, patch

from transaction_overrides import load_store, record_reprint, set_decision


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


def test_remote_store_uses_upstash_rest_env():
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {
            "result": json.dumps(
                {
                    "version": 1,
                    "transactions": {"tx-1": {"decision": "exclude"}},
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
    request = mock_urlopen.call_args[0][0]
    assert request.full_url == "https://redis.example.com"
    assert request.headers["Authorization"] == "Bearer token"

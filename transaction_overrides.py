import json
import os
import tempfile
import hashlib
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from urllib.request import Request, urlopen


ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STORE_PATH = os.environ.get(
    "BUDGET_DASHBOARD_STORE",
    os.path.join(ROOT, "data", "transaction_overrides.json"),
)
STORE_KEY = os.environ.get("BUDGET_DASHBOARD_STORE_KEY", "budget-display:transaction-overrides")
VALID_DECISIONS = {"auto", "include", "exclude"}
PROVISIONAL_ATTEMPT_LIMIT = int(os.environ.get("PROVISIONAL_ATTEMPT_LIMIT", "25"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_store() -> dict:
    return {
        "version": 1,
        "transactions": {},
        "provisional_transactions": {},
        "provisional_attempts": [],
        "reprint": {},
    }


def _normalize_store(store: dict) -> dict:
    store.setdefault("version", 1)
    store.setdefault("transactions", {})
    store.setdefault("provisional_transactions", {})
    store.setdefault("provisional_attempts", [])
    store.setdefault("reprint", {})
    return store


def _remote_config() -> tuple[str, str] | None:
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        return None
    return url, token


def _uses_remote_store(path: str) -> bool:
    return path == DEFAULT_STORE_PATH and _remote_config() is not None


def _upstash_command(command: list) -> object:
    config = _remote_config()
    if config is None:
        raise RuntimeError("UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN are required")

    url, token = config
    body = json.dumps(command).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload.get("result")


def _load_remote_store() -> dict:
    result = _upstash_command(["GET", STORE_KEY])
    if result is None:
        return _empty_store()
    if not isinstance(result, str):
        return _empty_store()

    store = json.loads(result)
    if not isinstance(store, dict):
        return _empty_store()
    return _normalize_store(store)


def _write_remote_store(store: dict) -> None:
    _upstash_command(["SET", STORE_KEY, json.dumps(store, sort_keys=True)])


def load_store(path: str = DEFAULT_STORE_PATH) -> dict:
    if _uses_remote_store(path):
        return _load_remote_store()

    if not os.path.exists(path):
        return _empty_store()
    with open(path, encoding="utf-8") as f:
        store = json.load(f)

    if not isinstance(store, dict):
        return _empty_store()
    return _normalize_store(store)


def write_store(store: dict, path: str = DEFAULT_STORE_PATH) -> None:
    if _uses_remote_store(path):
        _write_remote_store(store)
        return

    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".transaction_overrides.", suffix=".json", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def load_overrides(path: str = DEFAULT_STORE_PATH) -> dict:
    return load_store(path)["transactions"]


def load_provisional_transactions(path: str = DEFAULT_STORE_PATH) -> dict:
    return load_store(path)["provisional_transactions"]


def load_provisional_attempts(path: str = DEFAULT_STORE_PATH) -> list[dict]:
    attempts = load_store(path)["provisional_attempts"]
    return attempts if isinstance(attempts, list) else []


def _payload_value(payload: dict, key: str, default=None):
    return payload.get(key, payload.get(key.title(), default))


def _clean_text(value, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _parse_amount_milliunits(value) -> int:
    if value is None or value == "":
        raise ValueError("amount is required")

    if isinstance(value, str):
        amount_text = value.strip().replace(",", "").replace("$", "")
        amount_text = amount_text.replace("−", "-")
        if amount_text.startswith("(") and amount_text.endswith(")"):
            amount_text = f"-{amount_text[1:-1]}"
    else:
        amount_text = str(value)

    try:
        amount = Decimal(amount_text)
    except InvalidOperation as exc:
        raise ValueError("amount must be a number") from exc

    milliunits = int((abs(amount) * Decimal("1000")).quantize(Decimal("1")))
    if milliunits == 0:
        raise ValueError("amount must be non-zero")
    return milliunits


def _normalize_occurred_at(value) -> str:
    text = _clean_text(value)
    if not text:
        return _now()
    return text


def _provisional_id(entry: dict) -> str:
    fingerprint = json.dumps(
        {
            "source": entry["source"].casefold(),
            "merchant": entry["merchant"].casefold(),
            "card": entry["card"].casefold(),
            "amount_milliunits": entry["amount_milliunits"],
            "occurred_at": entry["occurred_at"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"prov-{digest}"


def record_provisional_transaction(payload: dict, path: str = DEFAULT_STORE_PATH) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("JSON object payload is required")

    occurred_at = _normalize_occurred_at(_payload_value(payload, "occurred_at"))
    entry = {
        "source": _clean_text(_payload_value(payload, "source"), "apple_wallet"),
        "merchant": _clean_text(_payload_value(payload, "merchant"), "Unknown merchant"),
        "amount_milliunits": _parse_amount_milliunits(_payload_value(payload, "amount")),
        "card": _clean_text(_payload_value(payload, "card")),
        "occurred_at": occurred_at,
        "memo": _clean_text(_payload_value(payload, "memo")),
        "status": "pending",
        "raw": payload,
    }
    entry["id"] = _provisional_id(entry)

    store = load_store(path)
    transactions = store["provisional_transactions"]
    existing = transactions.get(entry["id"])
    now = _now()
    if isinstance(existing, dict):
        existing["last_seen_at"] = now
        existing["seen_count"] = int(existing.get("seen_count", 1)) + 1
        existing["raw"] = payload
        existing["status"] = existing.get("status") or "pending"
        transactions[entry["id"]] = existing
        result = existing
    else:
        entry["created_at"] = now
        entry["last_seen_at"] = now
        entry["seen_count"] = 1
        transactions[entry["id"]] = entry
        result = entry

    write_store(store, path)
    return result


def record_provisional_attempt(
    payload: dict,
    status: str,
    error: str = "",
    transaction_id: str = "",
    path: str = DEFAULT_STORE_PATH,
) -> dict:
    store = load_store(path)
    attempts = store["provisional_attempts"]
    if not isinstance(attempts, list):
        attempts = []
        store["provisional_attempts"] = attempts

    attempt = {
        "received_at": _now(),
        "status": status,
        "error": error,
        "transaction_id": transaction_id,
        "payload": payload if isinstance(payload, dict) else {},
    }
    attempts.append(attempt)
    del attempts[:-PROVISIONAL_ATTEMPT_LIMIT]
    write_store(store, path)
    return attempt


def set_decision(line_id: str, decision: str, path: str = DEFAULT_STORE_PATH) -> dict:
    if not line_id:
        raise ValueError("line_id is required")
    if decision not in VALID_DECISIONS:
        raise ValueError("decision must be auto, include, or exclude")

    store = load_store(path)
    transactions = store["transactions"]
    if decision == "auto":
        transactions.pop(line_id, None)
    else:
        transactions[line_id] = {
            "decision": decision,
            "updated_at": _now(),
        }
    write_store(store, path)
    return transactions


def record_reprint(metadata: dict, path: str = DEFAULT_STORE_PATH) -> dict:
    store = load_store(path)
    previous_count = int(store.get("reprint", {}).get("count", 0))
    store["reprint"] = {
        "count": previous_count + 1,
        "requested_at": _now(),
        "metadata": metadata,
    }
    write_store(store, path)
    return store["reprint"]

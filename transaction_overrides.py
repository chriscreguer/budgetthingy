import json
import os
import tempfile
from datetime import datetime, timezone
from urllib.request import Request, urlopen


ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STORE_PATH = os.environ.get(
    "BUDGET_DASHBOARD_STORE",
    os.path.join(ROOT, "data", "transaction_overrides.json"),
)
STORE_KEY = os.environ.get("BUDGET_DASHBOARD_STORE_KEY", "budget-display:transaction-overrides")
VALID_DECISIONS = {"auto", "include", "exclude"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_store() -> dict:
    return {
        "version": 1,
        "transactions": {},
        "reprint": {},
    }


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
    store.setdefault("version", 1)
    store.setdefault("transactions", {})
    store.setdefault("reprint", {})
    return store


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
    store.setdefault("version", 1)
    store.setdefault("transactions", {})
    store.setdefault("reprint", {})
    return store


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

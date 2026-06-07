from api.generate import _build_budget_bin


def _load_budget_bin() -> bytes:
    body, _ = _build_budget_bin()
    return body

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from budget_pace import build_budget_bin
from transaction_overrides import load_store

BIN_NAME = "budget.bin"


def _build_budget_bin() -> tuple[bytes, dict]:
    data, metadata = build_budget_bin(load_store())
    metadata["path"] = BIN_NAME
    return data, metadata


def _generate_summary() -> dict:
    _, metadata = _build_budget_bin()
    return metadata

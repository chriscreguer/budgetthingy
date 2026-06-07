import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from budget_pace import SHIP_VARIANT, calculate_pace, fetch_flexible_totals, render_png
from convert_image import convert

BIN_NAME = "budget.bin"


def _build_budget_bin() -> tuple[bytes, dict]:
    assigned, spent = fetch_flexible_totals()
    pace_ratio, state_label, expected = calculate_pace(assigned, spent)

    with tempfile.TemporaryDirectory() as tmp:
        png_path = os.path.join(tmp, "budget.png")
        bin_path = os.path.join(tmp, BIN_NAME)

        render_png(
            assigned,
            spent,
            expected,
            pace_ratio,
            state_label,
            png_path,
            SHIP_VARIANT,
            tracking=-3,
        )
        byte_count = convert(png_path, bin_path)

        with open(bin_path, "rb") as f:
            data = f.read()

    metadata = {
        "ok": True,
        "path": BIN_NAME,
        "bytes": byte_count,
        "state": state_label,
        "pace": round(pace_ratio, 4),
        "spent": spent,
        "assigned": assigned,
        "expected": expected,
    }
    return data, metadata


def _generate_summary() -> dict:
    _, metadata = _build_budget_bin()
    return metadata

import os
import sys
import tempfile

from vercel.blob import AsyncBlobClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from budget_pace import SHIP_VARIANT, calculate_pace, fetch_flexible_totals, render_png
from convert_image import convert

BLOB_PATH = "budget.bin"
BLOB_ACCESS = "private"


async def _generate_and_upload() -> dict:
    assigned, spent = fetch_flexible_totals()
    pace_ratio, state_label, expected = calculate_pace(assigned, spent)

    with tempfile.TemporaryDirectory() as tmp:
        png_path = os.path.join(tmp, "budget.png")
        bin_path = os.path.join(tmp, BLOB_PATH)

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

    client = AsyncBlobClient()
    uploaded = await client.put(
        BLOB_PATH,
        data,
        access=BLOB_ACCESS,
        content_type="application/octet-stream",
        add_random_suffix=False,
        overwrite=True,
        cache_control_max_age=60,
    )

    return {
        "ok": True,
        "path": BLOB_PATH,
        "bytes": byte_count,
        "state": state_label,
        "pace": round(pace_ratio, 4),
        "spent": spent,
        "assigned": assigned,
        "expected": expected,
        "blob": dict(uploaded),
    }

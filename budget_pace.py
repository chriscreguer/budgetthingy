import calendar
import os
import sys
from datetime import date

import requests

import config

_WIDTH = 792
_HEIGHT = 272
_HALF = _HEIGHT // 2
_PAD = 40
_BAR_H = 30
_BAR_TOP = _HALF + 36
_FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "RobotoBold.ttf")


def fetch_flexible_totals() -> tuple[float, float]:
    """Returns (assigned_dollars, spent_dollars) for the Flexible category group."""
    if not config.API_TOKEN:
        raise ValueError("YNAB_API_TOKEN is not set in environment or .env")
    if not config.BUDGET_ID:
        raise ValueError("YNAB_BUDGET_ID is not set in environment or .env")

    url = f"https://api.ynab.com/v1/budgets/{config.BUDGET_ID}/categories"
    headers = {"Authorization": f"Bearer {config.API_TOKEN}"}

    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()

    groups = resp.json()["data"]["category_groups"]
    for group in groups:
        if group["name"] == config.GROUP_NAME:
            cats = group["categories"]
            spent = sum(-c["activity"] for c in cats) / 1000
            assigned = config.FLEXIBLE_BUDGET if config.FLEXIBLE_BUDGET > 0 else sum(c["budgeted"] for c in cats) / 1000
            return assigned, spent

    raise ValueError(
        f"Category group '{config.GROUP_NAME}' not found in budget. "
        "Check FLEXIBLE_GROUP_NAME in .env."
    )


def calculate_pace(
    assigned: float,
    spent: float,
    day: int | None = None,
    days_in_month: int | None = None,
) -> tuple[float, str, float]:
    """Returns (pace_ratio, state_label, expected_dollars)."""
    today = date.today()
    if day is None:
        day = today.day
    if days_in_month is None:
        days_in_month = calendar.monthrange(today.year, today.month)[1]

    if assigned == 0:
        return 0.0, "On Track", 0.0

    expected = assigned * (day / days_in_month)
    pace = spent / expected if expected > 0 else 0.0

    if pace < 0.85:
        label = "Plenty of Room"
    elif pace < 1.10:
        label = "On Track"
    elif pace < 1.25:
        label = "Spend Cautiously"
    else:
        label = "Slow Down"

    return pace, label, expected


def _fit_font(draw, text: str, max_w: int, max_h: int, max_size: int = 120):
    from PIL import ImageFont
    for size in range(max_size, 8, -2):
        font = ImageFont.truetype(_FONT_PATH, size)
        bb = draw.textbbox((0, 0), text, font=font)
        if (bb[2] - bb[0]) <= max_w and (bb[3] - bb[1]) <= max_h:
            return font
    return ImageFont.truetype(_FONT_PATH, 10)


def render_png(
    assigned: float,
    spent: float,
    expected: float,
    pace_ratio: float,
    state_label: str,
    output_path: str = "output.png",
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("L", (_WIDTH, _HEIGHT), color=255)
    draw = ImageDraw.Draw(img)

    # --- Top half: auto-scaled state label ---
    max_w = _WIDTH - 2 * _PAD
    max_h = _HALF - 20
    font = _fit_font(draw, state_label, max_w, max_h)
    bb = draw.textbbox((0, 0), state_label, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    tx = (_WIDTH - tw) // 2 - bb[0]
    ty = (_HALF - th) // 2 - bb[1]
    draw.text((tx, ty), state_label, fill=0, font=font)

    # --- Bottom half: progress bar ---
    bar_left = _PAD
    bar_right = _WIDTH - _PAD
    bar_width = bar_right - bar_left

    draw.rectangle(
        [bar_left, _BAR_TOP, bar_right, _BAR_TOP + _BAR_H],
        outline=0,
        width=2,
    )

    if assigned > 0:
        fill_frac = min(spent / assigned, 1.0)
        fill_right = bar_left + int(fill_frac * bar_width)
        if fill_right > bar_left:
            draw.rectangle(
                [bar_left, _BAR_TOP, fill_right, _BAR_TOP + _BAR_H],
                fill=0,
            )

        tick_frac = min(expected / assigned, 1.0)
        tick_x = bar_left + int(tick_frac * bar_width)
        draw.rectangle(
            [tick_x - 2, _BAR_TOP - 6, tick_x + 2, _BAR_TOP + _BAR_H + 6],
            fill=0,
        )

    small_font = ImageFont.truetype(_FONT_PATH, 18)
    label_text = f"${spent:,.0f} of ${assigned:,.0f}"
    bb2 = draw.textbbox((0, 0), label_text, font=small_font)
    lw = bb2[2] - bb2[0]
    lx = (_WIDTH - lw) // 2 - bb2[0]
    ly = _BAR_TOP + _BAR_H + 10
    draw.text((lx, ly), label_text, fill=0, font=small_font)

    img.save(output_path)


def main() -> None:
    try:
        assigned, spent = fetch_flexible_totals()
        pace_ratio, state_label, expected = calculate_pace(assigned, spent)
        render_png(assigned, spent, expected, pace_ratio, state_label)
        print(
            f"{state_label} | pace={pace_ratio:.2f} "
            f"| ${spent:,.0f} of ${assigned:,.0f} "
            f"(expected ${expected:,.0f})"
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

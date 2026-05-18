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

# Color palette definitions for different e-ink display types.
# Each palette drives mode, background, and per-element colors.
# "gray4" uses 4 discrete gray levels; "byr" uses black/yellow/red on white (RGB).
_PALETTES: dict[str, dict] = {
    "gray4": {
        "mode": "L",
        "background": 255,          # white
        "state_colors": {           # all black — color carries no meaning on gray4
            "Plenty of Room": 0,
            "On track": 0,
            "Spend Cautiously": 0,
            "Slow down": 0,
        },
        "bar_outline": 0,           # black
        "bar_fill": 80,             # dark gray for spent portion
        "bar_overage": 0,           # black when overspent (same, no color)
        "tick": 0,                  # black tick
        "label_text": 100,          # medium gray for secondary dollar label
    },
    "byr": {
        "mode": "RGB",
        "background": (255, 255, 255),   # white
        "state_colors": {
            "Plenty of Room": (0, 0, 0),
            "On track": (0, 0, 0),
            "Spend Cautiously": (180, 120, 0),   # dark amber
            "Slow down": (210, 30, 30),           # red
        },
        "bar_outline": (0, 0, 0),
        "bar_fill": (0, 0, 0),               # black for on-pace portion
        "bar_overage": (210, 30, 30),        # red when overspent
        "tick": (180, 130, 0),               # amber tick mark
        "label_text": (0, 0, 0),
    },
}


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
        return 0.0, "On track", 0.0

    expected = assigned * (day / days_in_month)
    pace = spent / expected if expected > 0 else 0.0

    if pace < 0.85:
        label = "Plenty of Room"
    elif pace < 1.10:
        label = "On track"
    elif pace < 1.25:
        label = "Spend Cautiously"
    else:
        label = "Slow down"

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
    variant: str = "gray4",
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    p = _PALETTES[variant]
    img = Image.new(p["mode"], (_WIDTH, _HEIGHT), color=p["background"])
    draw = ImageDraw.Draw(img)

    # --- Top half: auto-scaled state label, biased toward the bar ---
    max_w = _WIDTH - 2 * _PAD
    max_h = _HALF - 20
    font = _fit_font(draw, state_label, max_w, max_h, max_size=96)
    bb = draw.textbbox((0, 0), state_label, font=font)
    th = bb[3] - bb[1]
    tx = _PAD - bb[0]
    ty = (_HALF - th) // 2 - bb[1] + 16   # shift down toward bar
    draw.text((tx, ty), state_label, fill=p["state_colors"][state_label], font=font)

    # --- Bottom half: progress bar ---
    bar_left = _PAD
    bar_right = _WIDTH - _PAD
    bar_width = bar_right - bar_left

    draw.rectangle(
        [bar_left, _BAR_TOP, bar_right, _BAR_TOP + _BAR_H],
        outline=p["bar_outline"],
        width=2,
    )

    if assigned > 0:
        fill_frac = min(spent / assigned, 1.0)
        fill_right = bar_left + int(fill_frac * bar_width)
        tick_frac = min(expected / assigned, 1.0)
        tick_x = bar_left + int(tick_frac * bar_width)

        if fill_right > bar_left:
            if spent <= expected:
                draw.rectangle(
                    [bar_left, _BAR_TOP, fill_right, _BAR_TOP + _BAR_H],
                    fill=p["bar_fill"],
                )
            else:
                # On-pace portion in normal fill color, overage portion in overage color
                draw.rectangle(
                    [bar_left, _BAR_TOP, tick_x, _BAR_TOP + _BAR_H],
                    fill=p["bar_fill"],
                )
                draw.rectangle(
                    [tick_x, _BAR_TOP, fill_right, _BAR_TOP + _BAR_H],
                    fill=p["bar_overage"],
                )

        draw.rectangle(
            [tick_x - 3, _BAR_TOP - 20, tick_x + 3, _BAR_TOP + _BAR_H + 20],
            fill=p["tick"],
        )

    img.save(output_path)


def main() -> None:
    try:
        assigned, spent = fetch_flexible_totals()
        pace_ratio, state_label, expected = calculate_pace(assigned, spent)
        for variant, path in [("gray4", "output_gray4.png"), ("byr", "output_byr.png")]:
            render_png(assigned, spent, expected, pace_ratio, state_label, path, variant)
            print(f"  → {path}")
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

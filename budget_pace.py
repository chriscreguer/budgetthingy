import calendar
import os
import sys
from datetime import date

import requests

import config
from convert_image import convert

_WIDTH = 792
_HEIGHT = 272
_HALF = _HEIGHT // 2
_PAD = 40
_BAR_H = 30
_BAR_TOP = _HALF + 36
_FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "CrimsonText-Regular.ttf")

# Color palette definitions for different e-ink display types.
# Each palette drives mode, background, and per-element colors.
# "gray4" uses 4 discrete gray levels; "byr" uses black/yellow/red on white (RGB).
_PALETTES: dict[str, dict] = {
    "gray4": {
        "mode": "L",
        "background": 255,          # white
        "state_colors": {
            "On Track": 0,
            "Slow down": 0,
        },
        "bar_outline": 0,           # black
        "bar_fill": 0,              # black for on-track portion
        "bar_overage": 170,         # light gray for overage portion
        "tick": 0,                  # black tick
        "label_text": 100,          # medium gray for secondary dollar label
    },
    "byr": {
        "mode": "RGB",
        "background": (255, 255, 255),   # white
        "state_colors": {
            "On Track": (0, 0, 0),
            "Slow down": (0, 0, 0),
        },
        "bar_outline": (0, 0, 0),
        "bar_fill": (0, 0, 0),               # black for on-pace portion
        "bar_overage": (210, 30, 30),        # red when overspent
        "tick": (180, 130, 0),               # amber tick mark (maps to panel yellow)
        "label_text": (0, 0, 0),
        "font_path": "Merriweather-VF.ttf",
        "font_variation": "Bold",
        "centered": False,
        "tick_half_w": 2,
    },
    "nyt": {
        "mode": "RGB",
        "background": (255, 255, 255),
        "state_colors": {
            "On Track": (10, 10, 10),
            "Slow down": (10, 10, 10),
        },
        "bar_outline": (10, 10, 10),
        "bar_fill": (10, 10, 10),
        "bar_overage": (148, 28, 28),        # dark editorial red
        "tick": (10, 10, 10),
        "label_text": (100, 100, 100),
        "font_path": "PlayfairDisplay-Bold.ttf",
        "centered": False,
        "tick_half_w": 2,
    },
    "nyt_gray": {
        "mode": "L",
        "background": 255,
        "state_colors": {
            "On Track": 0,
            "Slow down": 0,
        },
        "bar_outline": 0,
        "bar_fill": 0,                       # black for on-track portion
        "bar_overage": 170,                  # light gray for overage portion
        "tick": 0,
        "label_text": 120,
        "font_path": "PlayfairDisplay-Bold.ttf",
        "centered": False,
        "tick_half_w": 2,
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

    if pace <= 1.0:
        label = "On Track"
    else:
        label = "Slow down"

    return pace, label, expected


def _text_width_tracked(draw, text: str, font, tracking: int = 0) -> int:
    total = 0
    for i, char in enumerate(text):
        bb = draw.textbbox((0, 0), char, font=font)
        total += bb[2] - bb[0]
        if i < len(text) - 1:
            total += tracking
    return total


def _draw_text_tracked(draw, pos, text: str, font, fill, tracking: int = 0) -> None:
    x, y = pos
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        bb = draw.textbbox((0, 0), char, font=font)
        x += (bb[2] - bb[0]) + tracking


def _load_font(font_path: str, size: int, variation: str | None = None):
    """Load a TTF; for variable fonts, select a named instance (e.g. 'Bold')."""
    from PIL import ImageFont
    font = ImageFont.truetype(font_path, size)
    if variation:
        try:
            font.set_variation_by_name(variation)
        except (OSError, ValueError):
            pass  # not a variable font, or instance missing — keep default
    return font


def _fit_font(draw, text: str, max_w: int, max_h: int, tracking: int = 0, max_size: int = 120, font_path: str | None = None, font_variation: str | None = None):
    fp = font_path or _FONT_PATH
    for size in range(max_size, 8, -2):
        font = _load_font(fp, size, font_variation)
        w = _text_width_tracked(draw, text, font, tracking)
        bb = draw.textbbox((0, 0), text, font=font)
        if w <= max_w and (bb[3] - bb[1]) <= max_h:
            return font
    return _load_font(fp, 10, font_variation)


def render_png(
    assigned: float,
    spent: float,
    expected: float,
    pace_ratio: float,
    state_label: str,
    output_path: str = "output.png",
    variant: str = "nyt",
    tracking: int = 0,
    width: int = _WIDTH,
    height: int = _HEIGHT,
    max_font_size: int = 96,
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    sx = width / _WIDTH
    sy = height / _HEIGHT
    half = height // 2
    pad = int(_PAD * sx)
    bar_h = int(_BAR_H * sy)
    bar_top = half + int(36 * sy)
    tick_ext = int(20 * sy)

    p = _PALETTES[variant]
    fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    fp = os.path.join(fonts_dir, p["font_path"]) if "font_path" in p else _FONT_PATH
    centered = p.get("centered", False)
    font_variation = p.get("font_variation")
    tick_hw = int(p.get("tick_half_w", 3) * sx)

    img = Image.new(p["mode"], (width, height), color=p["background"])
    draw = ImageDraw.Draw(img)

    # --- Optional kicker line above the label ---
    label_top = 0
    if "kicker" in p:
        kicker_size = int(13 * sy)
        kicker_font = _load_font(fp, kicker_size, font_variation)
        kicker_tracking = int(4 * sx)
        kw = _text_width_tracked(draw, p["kicker"], kicker_font, kicker_tracking)
        kx = (width - kw) // 2
        ky = int(18 * sy)
        _draw_text_tracked(draw, (kx, ky), p["kicker"], font=kicker_font, fill=p["label_text"], tracking=kicker_tracking)
        label_top = ky + int(18 * sy)

    # --- Optional thin rule at the half-way divider ---
    if "rule_color" in p:
        draw.line([(0, half), (width, half)], fill=p["rule_color"], width=1)

    # --- Top half: auto-scaled state label ---
    max_w = width - 2 * pad
    max_h = half - label_top - 10
    font = _fit_font(draw, state_label, max_w, max_h, tracking=tracking, max_size=max_font_size, font_path=fp, font_variation=font_variation)
    bb = draw.textbbox((0, 0), state_label, font=font)
    tw = _text_width_tracked(draw, state_label, font, tracking)
    th = bb[3] - bb[1]
    if centered:
        label_area_h = half - label_top
        ty = label_top + (label_area_h - th) // 2 - bb[1]
        tx = (width - tw) // 2 - bb[0]
    else:
        # Anchor from bar so gap stays consistent regardless of canvas height
        ty = bar_top - int(40 * sx) - th - bb[1]
        tx = pad - bb[0]
    _draw_text_tracked(draw, (tx, ty), state_label, font=font, fill=p["state_colors"][state_label], tracking=tracking)

    # --- Bottom half: progress bar ---
    bar_left = pad
    bar_right = width - pad
    bar_width = bar_right - bar_left

    if assigned > 0:
        fill_frac = min(spent / assigned, 1.0)
        fill_right = bar_left + int(fill_frac * bar_width)
        tick_frac = min(expected / assigned, 1.0)
        tick_x = bar_left + int(tick_frac * bar_width)

        if fill_right > bar_left:
            if spent <= expected:
                draw.rectangle(
                    [bar_left, bar_top, fill_right, bar_top + bar_h],
                    fill=p["bar_fill"],
                )
            else:
                draw.rectangle(
                    [bar_left, bar_top, tick_x, bar_top + bar_h],
                    fill=p["bar_fill"],
                )
                draw.rectangle(
                    [tick_x, bar_top, fill_right, bar_top + bar_h],
                    fill=p["bar_overage"],
                )

        draw.rectangle(
            [tick_x - tick_hw, bar_top - tick_ext, tick_x + tick_hw, bar_top + bar_h + tick_ext],
            fill=p["tick"],
        )

    # Draw outline last so it sits above the fill
    draw.rectangle(
        [bar_left, bar_top, bar_right, bar_top + bar_h],
        outline=p["bar_outline"],
        width=2,
    )

    img.save(output_path)


# The palette shipped to the ESP32 — its PNG is converted to budget.bin.
SHIP_VARIANT = "byr"
# Preview-only palettes rendered for visual comparison (skipped with --bin-only).
PREVIEW_VARIANTS = [("nyt", "output_nyt.png"), ("nyt_gray", "output_nyt_gray.png")]


def main() -> None:
    bin_only = "--bin-only" in sys.argv
    out_dir = os.path.dirname(os.path.abspath(__file__))
    ship_png = os.path.join(out_dir, f"output_{SHIP_VARIANT}.png")
    bin_path = os.path.join(out_dir, "budget.bin")

    try:
        assigned, spent = fetch_flexible_totals()
        pace_ratio, state_label, expected = calculate_pace(assigned, spent)

        if not bin_only:
            for variant, fname in PREVIEW_VARIANTS:
                path = os.path.join(out_dir, fname)
                render_png(assigned, spent, expected, pace_ratio, state_label, path, variant, tracking=-3)
                print(f"  → {path} ({os.path.getsize(path):,} bytes)")

        # Shipping variant: render PNG, then pack it into budget.bin for the ESP32.
        render_png(assigned, spent, expected, pace_ratio, state_label, ship_png, SHIP_VARIANT, tracking=-3)
        print(f"  → {ship_png} ({os.path.getsize(ship_png):,} bytes)")
        n = convert(ship_png, bin_path)
        print(f"  → {bin_path} ({n:,} bytes)")

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

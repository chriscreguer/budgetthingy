import calendar
import sys
from datetime import date

import requests

import config


def fetch_flexible_totals() -> tuple[float, float]:
    raise NotImplementedError


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


def render_png(
    assigned: float,
    spent: float,
    expected: float,
    pace_ratio: float,
    state_label: str,
    output_path: str = "output.png",
) -> None:
    raise NotImplementedError


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()

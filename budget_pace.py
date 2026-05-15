import calendar
import sys
from datetime import date

import requests

import config


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
            assigned = sum(c["budgeted"] for c in cats) / 1000
            spent = sum(-c["activity"] for c in cats) / 1000
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

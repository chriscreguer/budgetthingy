import calendar
import hashlib
import html
import os
import re
import sys
import tempfile
from datetime import date, datetime

import requests

import config
import savings
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


def _milliunits_to_dollars(amount: int) -> float:
    return amount / 1000


def _is_current_month(transaction: dict, today: date) -> bool:
    transaction_date = datetime.strptime(transaction["date"], "%Y-%m-%d").date()
    return transaction_date.year == today.year and transaction_date.month == today.month


def _is_excluded_payee(transaction: dict) -> bool:
    payee_name = (transaction.get("payee_name") or "").casefold()
    return any(pattern in payee_name for pattern in config.EXCLUDED_PAYEE_PATTERNS)


def _display_text(value: str | None, fallback: str = "") -> str:
    text = value or fallback
    return html.unescape(text)


def _display_account_name(account_name: str | None) -> str:
    account = _display_text(account_name, "Unknown account")
    if "costco anywhere visa" in account.casefold():
        return "Costco Citi"
    return account


def _normalize_decision(decision: str | None) -> str:
    if decision in {"include", "exclude"}:
        return decision
    return "auto"


def _override_decision(overrides: dict | None, line_id: str) -> str:
    if not overrides:
        return "auto"
    transactions = overrides.get("transactions", overrides)
    entry = transactions.get(line_id) if isinstance(transactions, dict) else None
    if isinstance(entry, dict):
        return _normalize_decision(entry.get("decision"))
    if isinstance(entry, str):
        return _normalize_decision(entry)
    return "auto"


def _store_budget(overrides: dict | None) -> float | None:
    """Returns the monthly budget saved in the app, or None when unset."""
    if not isinstance(overrides, dict):
        return None
    budget = overrides.get("budget")
    if not isinstance(budget, dict):
        return None
    monthly = budget.get("monthly")
    if monthly is None:
        return None
    try:
        return float(monthly)
    except (TypeError, ValueError):
        return None


def _resolve_assigned(
    overrides: dict | None,
    budget_categories: list[dict],
) -> tuple[float, str]:
    """Returns (assigned_dollars, source) from app budget, env var, then YNAB."""
    stored = _store_budget(overrides)
    if stored is not None and stored > 0:
        return stored, "app"
    if config.FLEXIBLE_BUDGET > 0:
        return config.FLEXIBLE_BUDGET, "env"
    return _milliunits_to_dollars(sum(c["budgeted"] for c in budget_categories)), "ynab"


def _store_provisional_transactions(overrides: dict | None) -> dict:
    if not isinstance(overrides, dict):
        return {}
    transactions = overrides.get("provisional_transactions")
    return transactions if isinstance(transactions, dict) else {}


def _fallback_line_id(
    transaction: dict,
    transaction_index: int,
    subtransaction: dict | None = None,
    subtransaction_index: int | None = None,
) -> str:
    pieces = [
        str(transaction.get("date", "")),
        str(transaction.get("amount", "")),
        str(transaction.get("payee_name", "")),
        str(transaction.get("memo", "")),
        str(transaction_index),
    ]
    if subtransaction is not None:
        pieces.extend(
            [
                str(subtransaction.get("amount", "")),
                str(subtransaction.get("memo", "")),
                str(subtransaction_index),
            ]
        )
    digest = hashlib.sha1("|".join(pieces).encode("utf-8")).hexdigest()[:16]
    return f"fallback-{digest}"


def _line_id(
    transaction: dict,
    transaction_index: int,
    subtransaction: dict | None = None,
    subtransaction_index: int | None = None,
) -> str:
    transaction_id = transaction.get("id") or _fallback_line_id(transaction, transaction_index)
    if subtransaction is None:
        return str(transaction_id)

    subtransaction_id = subtransaction.get("id")
    if subtransaction_id:
        return f"{transaction_id}:{subtransaction_id}"
    return _fallback_line_id(transaction, transaction_index, subtransaction, subtransaction_index)


def _category_context(groups: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    budget_categories = []
    category_lookup = {}

    for group in groups:
        group_name = group.get("name", "")
        group_internal = bool(group.get("internal")) or group_name == "Internal Master Category"
        group_hidden = bool(group.get("hidden") or group.get("deleted") or group_internal)

        for category in group.get("categories", []):
            category_id = category.get("id")
            if not category_id:
                continue

            category_lookup[category_id] = {
                "id": category_id,
                "name": category.get("name") or "Uncategorized",
                "group_name": group_name or "Uncategorized",
                "hidden": bool(category.get("hidden") or category.get("deleted") or group_hidden),
            }

            if group_hidden or category.get("hidden") or category.get("deleted"):
                continue
            budget_categories.append(category)

    return budget_categories, category_lookup


def _ynab_headers() -> dict[str, str]:
    if not config.API_TOKEN:
        raise ValueError("YNAB_API_TOKEN is not set in environment or .env")
    if not config.BUDGET_ID:
        raise ValueError("YNAB_BUDGET_ID is not set in environment or .env")
    return {"Authorization": f"Bearer {config.API_TOKEN}"}


def _fetch_ynab_category_groups(headers: dict[str, str]) -> list[dict]:
    url = f"https://api.ynab.com/v1/budgets/{config.BUDGET_ID}/categories"
    categories_resp = requests.get(url, headers=headers, timeout=10)
    categories_resp.raise_for_status()
    return categories_resp.json()["data"]["category_groups"]


def _fetch_ynab_accounts(headers: dict[str, str]) -> list[dict]:
    """Account types let the savings math spot credit card payments that the
    bank imported as ordinary transactions instead of linked YNAB transfers."""
    url = f"https://api.ynab.com/v1/budgets/{config.BUDGET_ID}/accounts"
    accounts_resp = requests.get(url, headers=headers, timeout=10)
    accounts_resp.raise_for_status()
    return accounts_resp.json()["data"]["accounts"]


def _fetch_ynab_transactions(headers: dict[str, str], today: date) -> list[dict]:
    # Reaches back far enough to cover the savings chart window, so the pace
    # math and every month of savings come from one response.
    since_date = savings.history_since_date(today)
    transactions_url = f"https://api.ynab.com/v1/budgets/{config.BUDGET_ID}/transactions"
    transactions_resp = requests.get(
        transactions_url,
        headers=headers,
        params={"since_date": since_date},
        timeout=10,
    )
    transactions_resp.raise_for_status()
    return transactions_resp.json()["data"]["transactions"]


def _default_line_status(
    transaction: dict,
    amount_source: dict,
) -> tuple[bool, str]:
    if _is_excluded_payee(transaction):
        return False, "payee rule"
    if amount_source.get("transfer_account_id"):
        return False, "transfer"
    return True, "spending"


def _transaction_line(
    transaction: dict,
    transaction_index: int,
    amount_source: dict,
    category_id: str | None,
    category_lookup: dict[str, dict],
    overrides: dict | None,
    subtransaction: dict | None = None,
    subtransaction_index: int | None = None,
) -> dict | None:
    raw_amount = amount_source.get("amount", 0)
    outflow_milliunits = max(0, -raw_amount)
    if outflow_milliunits == 0:
        return None

    line_id = _line_id(transaction, transaction_index, subtransaction, subtransaction_index)
    default_included, default_reason = _default_line_status(
        transaction,
        amount_source,
    )
    decision = _override_decision(overrides, line_id)
    included = default_included
    reason = default_reason
    if decision == "include":
        included = True
        reason = "manual include"
    elif decision == "exclude":
        included = False
        reason = "manual exclude"

    category = category_lookup.get(category_id or "", {})
    category_name = (
        category.get("name")
        or amount_source.get("category_name")
        or transaction.get("category_name")
        or "Uncategorized"
    )
    return {
        "line_id": line_id,
        "transaction_id": transaction.get("id") or "",
        "subtransaction_id": (subtransaction or {}).get("id") or "",
        "date": transaction.get("date") or "",
        "payee": _display_text(transaction.get("payee_name"), "Uncategorized"),
        "memo": _display_text(amount_source.get("memo") or transaction.get("memo")),
        "account": _display_account_name(transaction.get("account_name")),
        "amount": _milliunits_to_dollars(outflow_milliunits),
        "amount_milliunits": outflow_milliunits,
        "category_id": category_id or "",
        "category": _display_text(category_name, "Uncategorized"),
        "category_group": _display_text(category.get("group_name"), "Uncategorized"),
        "default_included": default_included,
        "included": included,
        "decision": decision,
        "reason": reason,
        "cleared": transaction.get("cleared") or "",
        "approved": bool(transaction.get("approved", False)),
    }


def _transaction_lines(
    transactions: list[dict],
    today: date,
    category_lookup: dict[str, dict],
    overrides: dict | None,
) -> list[dict]:
    lines = []
    for transaction_index, transaction in enumerate(transactions):
        if transaction.get("deleted") or not _is_current_month(transaction, today):
            continue

        subtransactions = transaction.get("subtransactions") or []
        if subtransactions:
            for subtransaction_index, subtransaction in enumerate(subtransactions):
                if subtransaction.get("deleted"):
                    continue
                line = _transaction_line(
                    transaction,
                    transaction_index,
                    subtransaction,
                    subtransaction.get("category_id"),
                    category_lookup,
                    overrides,
                    subtransaction=subtransaction,
                    subtransaction_index=subtransaction_index,
                )
                if line is not None:
                    lines.append(line)
        else:
            line = _transaction_line(
                transaction,
                transaction_index,
                transaction,
                transaction.get("category_id"),
                category_lookup,
                overrides,
            )
            if line is not None:
                lines.append(line)

    return sorted(lines, key=lambda item: (item["date"], item["payee"], item["amount"]), reverse=True)


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _provisional_date(transaction: dict) -> str:
    direct_date = _parse_iso_date(transaction.get("date"))
    if direct_date is not None:
        return direct_date.isoformat()

    occurred_at = _parse_iso_date(transaction.get("occurred_at"))
    if occurred_at is not None:
        return occurred_at.isoformat()

    return date.today().isoformat()


_GENERIC_MATCH_WORDS = {
    "card",
    "checkout",
    "inc",
    "llc",
    "market",
    "online",
    "pay",
    "payment",
    "purchase",
    "store",
    "the",
}


def _match_words(value: str | None) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", (value or "").casefold()))
    return {word for word in words if len(word) >= 4 and word not in _GENERIC_MATCH_WORDS}


def _similar_text(left: str | None, right: str | None) -> bool:
    left_words = _match_words(left)
    right_words = _match_words(right)
    if not left_words or not right_words:
        return False

    left_joined = " ".join(sorted(left_words))
    right_joined = " ".join(sorted(right_words))
    return bool(
        left_words & right_words
        or left_joined in right_joined
        or right_joined in left_joined
    )


def _known_account(account: str | None) -> bool:
    return bool(account and account != "Unknown account")


def _matches_ynab_line(provisional: dict, ynab_line: dict) -> bool:
    if ynab_line.get("provisional"):
        return False

    try:
        provisional_amount = int(provisional.get("amount_milliunits", 0))
        ynab_amount = int(ynab_line.get("amount_milliunits", 0))
    except (TypeError, ValueError):
        return False
    if provisional_amount <= 0 or provisional_amount != ynab_amount:
        return False

    provisional_date = _parse_iso_date(_provisional_date(provisional))
    ynab_date = _parse_iso_date(ynab_line.get("date"))
    if provisional_date is None or ynab_date is None:
        return False
    if abs((provisional_date - ynab_date).days) > 10:
        return False

    if not _similar_text(provisional.get("merchant"), ynab_line.get("payee")):
        return False

    card = provisional.get("card")
    account = ynab_line.get("account")
    if card and _known_account(account) and not _similar_text(card, account):
        return False

    return True


def _matching_ynab_line(provisional: dict, ynab_lines: list[dict]) -> dict | None:
    for line in ynab_lines:
        if _matches_ynab_line(provisional, line):
            return line
    return None


def _provisional_line(
    transaction: dict,
    ynab_lines: list[dict],
    overrides: dict | None,
) -> dict | None:
    try:
        amount_milliunits = int(transaction.get("amount_milliunits", 0))
    except (TypeError, ValueError):
        return None
    if amount_milliunits <= 0:
        return None

    line_id = str(transaction.get("id") or _fallback_line_id(transaction, 0))
    matched_line = _matching_ynab_line(transaction, ynab_lines)
    default_included = matched_line is None
    default_reason = "pending" if default_included else "matched ynab"
    decision = _override_decision(overrides, line_id)
    included = default_included
    reason = default_reason
    if decision == "include":
        included = True
        reason = "manual include"
    elif decision == "exclude":
        included = False
        reason = "manual exclude"

    source = _display_text(transaction.get("source"), "provisional")
    memo = _display_text(transaction.get("memo")) or f"source={source}"
    return {
        "line_id": line_id,
        "transaction_id": "",
        "subtransaction_id": "",
        "date": _provisional_date(transaction),
        "payee": _display_text(transaction.get("merchant"), "Unknown merchant"),
        "memo": memo,
        "account": _display_account_name(transaction.get("card")) if transaction.get("card") else "Wallet",
        "amount": _milliunits_to_dollars(amount_milliunits),
        "amount_milliunits": amount_milliunits,
        "category_id": "",
        "category": "Pending",
        "category_group": "Provisional",
        "default_included": default_included,
        "included": included,
        "decision": decision,
        "reason": reason,
        "cleared": "pending",
        "approved": False,
        "provisional": True,
        "source": source,
        "matched_transaction_id": (matched_line or {}).get("transaction_id") or (matched_line or {}).get("line_id", ""),
    }


def _provisional_lines(
    provisional_transactions: dict,
    today: date,
    ynab_lines: list[dict],
    overrides: dict | None,
) -> list[dict]:
    lines = []
    for transaction in provisional_transactions.values():
        if not isinstance(transaction, dict):
            continue
        if transaction.get("deleted"):
            continue
        transaction_date = {"date": _provisional_date(transaction)}
        if not _is_current_month(transaction_date, today):
            continue
        line = _provisional_line(transaction, ynab_lines, overrides)
        if line is not None and not line.get("matched_transaction_id"):
            lines.append(line)
    return lines


def fetch_budget_snapshot(overrides: dict | None = None, today: date | None = None) -> dict:
    """Returns detailed budget pace data with per-purchase inclusion decisions."""
    today = today or date.today()
    headers = _ynab_headers()
    groups = _fetch_ynab_category_groups(headers)
    budget_categories, category_lookup = _category_context(groups)

    accounts = _fetch_ynab_accounts(headers)
    transactions = _fetch_ynab_transactions(headers, today)
    ynab_lines = _transaction_lines(
        transactions,
        today,
        category_lookup,
        overrides,
    )
    provisional_lines = _provisional_lines(
        _store_provisional_transactions(overrides),
        today,
        ynab_lines,
        overrides,
    )
    lines = sorted(
        ynab_lines + provisional_lines,
        key=lambda item: (item["date"], item["payee"], item["amount"]),
        reverse=True,
    )
    spent = sum(line["amount"] for line in lines if line["included"])
    assigned, budget_source = _resolve_assigned(overrides, budget_categories)
    savings_summary = savings.savings_summary(transactions, today, accounts)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    pace_ratio, state_label, expected = calculate_pace(
        assigned,
        spent,
        day=today.day,
        days_in_month=days_in_month,
    )

    category_totals_by_id = {}
    account_totals_by_name = {}
    excluded_reasons = {}
    for line in lines:
        if not line["included"]:
            excluded_reasons[line["reason"]] = excluded_reasons.get(line["reason"], 0) + 1
            continue

        account_key = line["account"] or "Unknown account"
        if account_key not in account_totals_by_name:
            account_totals_by_name[account_key] = {
                "account": account_key,
                "spent": 0.0,
                "count": 0,
            }
        account_totals_by_name[account_key]["spent"] += line["amount"]
        account_totals_by_name[account_key]["count"] += 1

        category_key = line["category_id"] or "uncategorized"
        if category_key not in category_totals_by_id:
            category_totals_by_id[category_key] = {
                "category_id": line["category_id"],
                "category": line["category"],
                "category_group": line["category_group"],
                "spent": 0.0,
            }
        category_totals_by_id[category_key]["spent"] += line["amount"]

    return {
        "ok": True,
        "month": today.strftime("%Y-%m"),
        "day": today.day,
        "days_in_month": days_in_month,
        "assigned": assigned,
        "budget_source": budget_source,
        "spent": spent,
        "saved_last_month": savings_summary["saved_last_month"],
        "projected_savings": savings_summary["projected_savings"],
        "savings": {
            "last_month": savings_summary["last_month"],
            "this_month": savings_summary["this_month"],
            "history": savings_summary["history"],
        },
        "expected": expected,
        "remaining": assigned - spent,
        "pace": pace_ratio,
        "state": state_label,
        "progress": progress_bar_metrics(assigned, spent, expected),
        "transactions": lines,
        "category_totals": sorted(
            category_totals_by_id.values(),
            key=lambda item: item["spent"],
            reverse=True,
        ),
        "account_totals": sorted(
            account_totals_by_name.values(),
            key=lambda item: item["spent"],
            reverse=True,
        ),
        "excluded_reasons": [
            {"reason": reason, "count": count}
            for reason, count in sorted(excluded_reasons.items(), key=lambda item: item[1], reverse=True)
        ],
        "counts": {
            "included": sum(1 for line in lines if line["included"]),
            "excluded": sum(1 for line in lines if not line["included"]),
            "overridden": sum(1 for line in lines if line["decision"] != "auto"),
            "total": len(lines),
            "clearance": _clearance_counts(lines),
        },
    }


def fetch_flexible_totals(overrides: dict | None = None) -> tuple[float, float]:
    """Returns (assigned_dollars, spent_dollars) for current-month spending."""
    snapshot = fetch_budget_snapshot(overrides)
    return snapshot["assigned"], snapshot["spent"]


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

    if pace <= 1.0:
        label = "On Track"
    else:
        label = "Slow down"

    return pace, label, expected


def progress_bar_metrics(assigned: float, spent: float, expected: float) -> dict[str, float]:
    """Returns normalized e-ink progress-bar ratios for web and image rendering."""
    if assigned <= 0:
        return {
            "fill": 0.0,
            "tick": 0.0,
            "on_pace_fill": 0.0,
            "overage": 0.0,
        }

    fill = min(max(spent / assigned, 0.0), 1.0)
    tick = min(max(expected / assigned, 0.0), 1.0)
    overage = max(fill - tick, 0.0) if spent > expected else 0.0

    return {
        "fill": fill,
        "tick": tick,
        "on_pace_fill": tick if overage > 0 else fill,
        "overage": overage,
    }


def _clearance_counts(lines: list[dict]) -> dict[str, dict[str, int]]:
    statuses = ("cleared", "uncleared", "pending", "reconciled", "unknown")
    counts = {
        "total": dict.fromkeys(statuses, 0),
        "included": dict.fromkeys(statuses, 0),
    }

    for line in lines:
        status = (line.get("cleared") or "unknown").casefold()
        if status not in statuses:
            status = "unknown"
        counts["total"][status] += 1
        if line["included"]:
            counts["included"][status] += 1

    return counts


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
        progress = progress_bar_metrics(assigned, spent, expected)
        fill_right = bar_left + int(progress["fill"] * bar_width)
        tick_x = bar_left + int(progress["tick"] * bar_width)

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


def _build_budget_bin_in_dir(output_dir: str, overrides: dict | None = None, tracking: int = -3) -> tuple[bytes, dict]:
    snapshot = fetch_budget_snapshot(overrides)
    png_path = os.path.join(output_dir, f"output_{SHIP_VARIANT}.png")
    bin_path = os.path.join(output_dir, "budget.bin")

    render_png(
        snapshot["assigned"],
        snapshot["spent"],
        snapshot["expected"],
        snapshot["pace"],
        snapshot["state"],
        png_path,
        SHIP_VARIANT,
        tracking=tracking,
    )
    byte_count = convert(png_path, bin_path)

    with open(bin_path, "rb") as f:
        data = f.read()

    metadata = {
        "ok": True,
        "path": bin_path,
        "preview_path": png_path,
        "bytes": byte_count,
        "state": snapshot["state"],
        "pace": round(snapshot["pace"], 4),
        "spent": snapshot["spent"],
        "assigned": snapshot["assigned"],
        "expected": snapshot["expected"],
        "remaining": snapshot["remaining"],
        "counts": snapshot["counts"],
    }
    return data, metadata


def build_budget_bin(overrides: dict | None = None, output_dir: str | None = None, tracking: int = -3) -> tuple[bytes, dict]:
    """Builds the ESP32-ready frame, optionally writing budget.bin/output PNG."""
    if output_dir is not None:
        os.makedirs(output_dir, exist_ok=True)
        return _build_budget_bin_in_dir(output_dir, overrides, tracking)

    with tempfile.TemporaryDirectory() as tmp:
        data, metadata = _build_budget_bin_in_dir(tmp, overrides, tracking)
        metadata["path"] = "budget.bin"
        metadata["preview_path"] = f"output_{SHIP_VARIANT}.png"
        return data, metadata


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

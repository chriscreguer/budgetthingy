"""Month-over-month cash flow: what was saved last month, what this month projects to.

Savings is income minus spending straight from YNAB. Unlike the pace math in
budget_pace, these figures deliberately ignore manual Include/Exclude overrides
so the savings picture stays an unedited record of what actually moved.
"""

import calendar
import os
import re
from datetime import date, datetime

import config

# How many months the savings chart covers, current month included.
HISTORY_MONTHS = max(1, int(os.environ.get("SAVINGS_HISTORY_MONTHS", "12")))


def _transaction_date(transaction: dict) -> date | None:
    try:
        return datetime.strptime(transaction["date"], "%Y-%m-%d").date()
    except (KeyError, TypeError, ValueError):
        return None


def _is_excluded_payee(transaction: dict) -> bool:
    payee_name = (transaction.get("payee_name") or "").casefold()
    return any(pattern in payee_name for pattern in config.EXCLUDED_PAYEE_PATTERNS)


def _normalize_name(value: str | None) -> str:
    """Casefolds and collapses whitespace, including the non-breaking spaces
    YNAB keeps in some account names."""
    return re.sub(r"\s+", " ", (value or "").replace("\u00a0", " ")).strip().casefold()


def card_context(accounts: list[dict] | None) -> tuple[set[str], tuple[str, ...]]:
    """Returns (credit card account ids, normalized credit card account names)."""
    if not accounts:
        return set(), ()

    ids = set()
    names = []
    for account in accounts:
        if account.get("type") != "creditCard":
            continue
        if account.get("id"):
            ids.add(account["id"])
        name = _normalize_name(account.get("name"))
        if name:
            names.append(name)
    return ids, tuple(names)


def off_budget_ids(accounts: list[dict] | None) -> set[str]:
    """Ids of accounts outside the budget, such as a brokerage.

    Their movements are not household income or spending, and their
    reconciliation adjustments would otherwise read as enormous income.
    """
    if not accounts:
        return set()
    return {
        account["id"]
        for account in accounts
        if account.get("id") and account.get("on_budget") is False
    }


# Wording banks use for a card payoff. Anything else arriving on a card is
# treated as a refund, so a genuine payment is never mistaken for one.
_PAYMENT_WORDS = ("payment", "thank you", "autopay", "auto pay", "bill pay")

# How far back a refund may reach to find the purchase it reverses.
REFUND_MATCH_DAYS = 120

# YNAB bookkeeping rather than money moving in or out.
_ADJUSTMENT_WORDS = ("balance adjustment", "starting balance", "reconciliation")

# Movement between the user's own accounts that the bank imported as an ordinary
# transaction, so YNAB never linked it as a transfer.
_TRANSFER_WORDS = ("transfer",)


def _is_card_payoff_inflow(transaction: dict, card_names: tuple[str, ...]) -> bool:
    """True when money landing on a card is paying it off rather than refunding."""
    payee = _normalize_name(transaction.get("payee_name"))
    if not payee:
        return True
    if any(name and name in payee for name in card_names):
        return True
    return any(word in payee for word in _PAYMENT_WORDS)


def _is_card_payment(transaction: dict, card_names: tuple[str, ...]) -> bool:
    """True when an outflow is paying off a credit card.

    Banks often import a card payment as two ordinary transactions rather than a
    linked YNAB transfer. Counting the payment would double-count purchases that
    were already recorded on the card itself.
    """
    payee = _normalize_name(transaction.get("payee_name"))
    return any(name and name in payee for name in card_names)


def _candidate_purchases(
    purchases: dict[str, list[dict]],
    payee: str,
    refund_date: date,
    account_id: str | None,
) -> list[dict]:
    """Purchases a refund could reverse: same payee, same account, already made,
    still within the return window, and not already cancelled by another refund.

    The account has to match because a merchant refunds the card that paid. It
    also keeps unrelated money with a colliding payee apart, such as savings
    interest earned and credit card interest charged.

    Most recent first, since that is the likelier return.
    """
    if not payee:
        return []
    window_start = refund_date.toordinal() - REFUND_MATCH_DAYS
    matches = [
        purchase
        for purchase in purchases.get(payee, [])
        if purchase["remaining"] > 0
        and purchase["account_id"] == account_id
        and purchase["date"] <= refund_date
        and purchase["date"].toordinal() >= window_start
    ]
    matches.sort(key=lambda purchase: purchase["date"], reverse=True)
    return matches


def _has_matching_purchase(
    purchases: dict[str, list[dict]],
    payee: str,
    refund_date: date,
    account_id: str | None,
) -> bool:
    return bool(_candidate_purchases(purchases, payee, refund_date, account_id))


def _apply_refund(
    purchases: dict[str, list[dict]],
    payee: str,
    refund_date: date,
    amount: int,
    account_id: str | None,
) -> list[tuple[tuple[int, int], int]]:
    """Books a refund against the purchases it reverses.

    Returns (month, milliunits) pairs. Anything left over lands in the refund's
    own month, which is the best available answer when the purchase predates the
    fetched window.
    """
    applied = []
    remaining = amount
    for purchase in _candidate_purchases(purchases, payee, refund_date, account_id):
        if remaining <= 0:
            break
        take = min(remaining, purchase["remaining"])
        purchase["remaining"] -= take
        remaining -= take
        applied.append((purchase["month"], take))

    if remaining > 0:
        applied.append(((refund_date.year, refund_date.month), remaining))
    return applied


def _is_internal_movement(transaction: dict) -> bool:
    """True for bookkeeping entries and unlinked transfers between own accounts."""
    payee = _normalize_name(transaction.get("payee_name"))
    if not payee:
        return False
    return any(word in payee for word in _ADJUSTMENT_WORDS + _TRANSFER_WORDS)


def _counts_as_cash_flow(transaction: dict) -> bool:
    if transaction.get("deleted"):
        return False
    # Transfers move money between the user's own accounts. A credit card
    # payment would otherwise register as income and spending at once.
    if transaction.get("transfer_account_id"):
        return False
    if _is_internal_movement(transaction):
        return False
    return not _is_excluded_payee(transaction)


def _eligible_rows(transactions: list[dict]) -> list[tuple[date, dict]]:
    rows = []
    for transaction in transactions:
        if not _counts_as_cash_flow(transaction):
            continue
        transaction_date = _transaction_date(transaction)
        if transaction_date is None:
            continue
        rows.append((transaction_date, transaction))
    rows.sort(key=lambda row: row[0])
    return rows


def cash_flow_by_month(
    transactions: list[dict],
    accounts: list[dict] | None = None,
) -> dict[tuple[int, int], tuple[float, float]]:
    """Returns {(year, month): (income, spending)} in dollars.

    Split transactions are counted at the parent amount, which YNAB keeps equal
    to the sum of its subtransactions. Pass accounts to recognise credit card
    payments the bank imported as ordinary transactions instead of linked YNAB
    transfers.

    A refund is booked against the month of the purchase it reverses, not the
    month it arrives, so returning something does not make the month of the
    purchase look worse than it was.
    """
    card_ids, card_names = card_context(accounts)
    ignored_ids = off_budget_ids(accounts)
    rows = _eligible_rows(transactions)

    income: dict[tuple[int, int], int] = {}
    spending: dict[tuple[int, int], int] = {}
    purchases: dict[str, list[dict]] = {}
    refunds: list[tuple[date, str, int, str | None]] = []

    for row_date, transaction in rows:
        if transaction.get("account_id") in ignored_ids:
            continue

        key = (row_date.year, row_date.month)
        amount = transaction.get("amount", 0) or 0
        payee = _normalize_name(transaction.get("payee_name"))

        if amount < 0:
            if _is_card_payment(transaction, card_names):
                continue
            spending[key] = spending.get(key, 0) + -amount
            purchases.setdefault(payee, []).append(
                {
                    "date": row_date,
                    "month": key,
                    "remaining": -amount,
                    "account_id": transaction.get("account_id"),
                }
            )
            continue

        account_id = transaction.get("account_id")
        if account_id in card_ids:
            # Money landing on a card is a payoff or a refund, never income.
            if not _is_card_payoff_inflow(transaction, card_names):
                refunds.append((row_date, payee, amount, account_id))
            continue

        # Money arriving with a card's name on it is card business, not pay.
        if _is_card_payment(transaction, card_names):
            continue

        # An inflow elsewhere is income unless it reverses an earlier purchase
        # on the same account, which is how a debit card return arrives.
        if _has_matching_purchase(purchases, payee, row_date, account_id):
            refunds.append((row_date, payee, amount, account_id))
            continue
        income[key] = income.get(key, 0) + amount

    for refund_date, payee, amount, account_id in refunds:
        for month, applied in _apply_refund(purchases, payee, refund_date, amount, account_id):
            spending[month] = max(0, spending.get(month, 0) - applied)

    months = set(income) | set(spending)
    return {
        month: (income.get(month, 0) / 1000, spending.get(month, 0) / 1000)
        for month in months
    }


def month_cash_flow(
    transactions: list[dict],
    year: int,
    month: int,
    accounts: list[dict] | None = None,
) -> tuple[float, float]:
    """Returns (income, spending) in dollars for the given calendar month."""
    return cash_flow_by_month(transactions, accounts).get((year, month), (0.0, 0.0))


def previous_month(today: date) -> tuple[int, int]:
    """Returns (year, month) for the month before the one containing today."""
    return shift_month(today.year, today.month, -1)


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Returns (year, month) delta months away, normalized across year ends."""
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def savings_since_date(today: date, months_back: int = 1) -> str:
    """Returns the YNAB since_date covering months_back months before today."""
    year, month = shift_month(today.year, today.month, -months_back)
    return date(year, month, 1).isoformat()


def history_since_date(today: date) -> str:
    """Returns the YNAB since_date covering the whole savings chart window."""
    return savings_since_date(today, months_back=HISTORY_MONTHS - 1)


def _history_rows(
    by_month: dict[tuple[int, int], tuple[float, float]],
    today: date,
    history_months: int,
) -> list[dict]:
    """One row per month, oldest first, ending with the current month.

    Savings here is the true net, negative included, because the point of the
    chart is the shape over time. The tiles keep their own zero floor.

    Leading months with no activity at all are dropped so a budget that started
    part way through the window does not render as flat zero bars. Interior gaps
    stay, since a quiet month between two active ones is real.
    """
    rows = []
    for offset in range(history_months - 1, -1, -1):
        year, month = shift_month(today.year, today.month, -offset)
        income, spending = by_month.get((year, month), (0.0, 0.0))
        rows.append(
            {
                "month": f"{year:04d}-{month:02d}",
                "income": income,
                "spending": spending,
                "saved": income - spending,
                "partial": offset == 0,
                # Spending with nothing on record as income is a gap in the
                # data, not a month of pure overspending.
                "income_missing": not income and spending > 0,
            }
        )

    first_active = next(
        (i for i, row in enumerate(rows) if row["income"] or row["spending"]),
        len(rows) - 1,
    )
    return rows[first_active:]


def savings_summary(
    transactions: list[dict],
    today: date | None = None,
    accounts: list[dict] | None = None,
    history_months: int | None = None,
) -> dict:
    """Returns last month's savings and this month's projected savings.

    Both figures are floored at zero. This month's spending is extrapolated from
    the run rate so far; income is taken from last month, because paychecks
    arrive in lumps and extrapolating them by day swings wildly.
    """
    today = today or date.today()
    last_year, last_month_number = previous_month(today)

    by_month = cash_flow_by_month(transactions, accounts)
    last_income, last_spending = by_month.get((last_year, last_month_number), (0.0, 0.0))
    this_income, this_spending = by_month.get((today.year, today.month), (0.0, 0.0))

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    projected_spending = this_spending * days_in_month / today.day if today.day else this_spending
    projected_income = last_income if last_income > 0 else this_income

    saved_last_month = max(0.0, last_income - last_spending)
    projected_saved = max(0.0, projected_income - projected_spending)

    return {
        "last_month": {
            "month": f"{last_year:04d}-{last_month_number:02d}",
            "income": last_income,
            "spending": last_spending,
            "saved": saved_last_month,
        },
        "this_month": {
            "month": today.strftime("%Y-%m"),
            "income": this_income,
            "spending": this_spending,
            "projected_income": projected_income,
            "projected_spending": projected_spending,
            "projected_saved": projected_saved,
        },
        "saved_last_month": saved_last_month,
        "projected_savings": projected_saved,
        "history": _history_rows(
            by_month,
            today,
            history_months if history_months is not None else HISTORY_MONTHS,
        ),
    }

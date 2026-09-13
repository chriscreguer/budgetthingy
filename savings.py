"""Month-over-month cash flow: what was saved last month, what this month projects to.

Savings is income minus spending straight from YNAB. Unlike the pace math in
budget_pace, these figures deliberately ignore manual Include/Exclude overrides
so the savings picture stays an unedited record of what actually moved.
"""

import calendar
import re
from datetime import date, datetime

import config


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


# Wording banks use for a card payoff. Anything else arriving on a card is
# treated as a refund, so a genuine payment is never mistaken for one.
_PAYMENT_WORDS = ("payment", "thank you", "autopay", "auto pay", "bill pay")


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


def _counts_as_cash_flow(transaction: dict) -> bool:
    if transaction.get("deleted"):
        return False
    # Transfers move money between the user's own accounts. A credit card
    # payment would otherwise register as income and spending at once.
    if transaction.get("transfer_account_id"):
        return False
    return not _is_excluded_payee(transaction)


def month_cash_flow(
    transactions: list[dict],
    year: int,
    month: int,
    accounts: list[dict] | None = None,
) -> tuple[float, float]:
    """Returns (income, spending) in dollars for the given calendar month.

    Split transactions are counted at the parent amount, which YNAB keeps equal
    to the sum of its subtransactions. Pass accounts to filter out credit card
    payments that the bank imported as ordinary transactions instead of linked
    YNAB transfers.
    """
    card_ids, card_names = card_context(accounts)
    income_milliunits = 0
    spending_milliunits = 0
    refund_milliunits = 0

    for transaction in transactions:
        if not _counts_as_cash_flow(transaction):
            continue

        transaction_date = _transaction_date(transaction)
        if transaction_date is None:
            continue
        if transaction_date.year != year or transaction_date.month != month:
            continue

        amount = transaction.get("amount", 0) or 0
        if amount > 0:
            # Money landing on a credit card is a payoff or a refund, never
            # income. A refund means less was actually spent.
            if transaction.get("account_id") in card_ids:
                if not _is_card_payoff_inflow(transaction, card_names):
                    refund_milliunits += amount
                continue
            income_milliunits += amount
        else:
            if _is_card_payment(transaction, card_names):
                continue
            spending_milliunits += -amount

    net_spending = max(0, spending_milliunits - refund_milliunits)
    return income_milliunits / 1000, net_spending / 1000


def previous_month(today: date) -> tuple[int, int]:
    """Returns (year, month) for the month before the one containing today."""
    previous = date.fromordinal(today.replace(day=1).toordinal() - 1)
    return previous.year, previous.month


def savings_since_date(today: date) -> str:
    """Returns the YNAB since_date covering last month through today."""
    year, month = previous_month(today)
    return date(year, month, 1).isoformat()


def savings_summary(
    transactions: list[dict],
    today: date | None = None,
    accounts: list[dict] | None = None,
) -> dict:
    """Returns last month's savings and this month's projected savings.

    Both figures are floored at zero. This month's spending is extrapolated from
    the run rate so far; income is taken from last month, because paychecks
    arrive in lumps and extrapolating them by day swings wildly.
    """
    today = today or date.today()
    last_year, last_month_number = previous_month(today)

    last_income, last_spending = month_cash_flow(transactions, last_year, last_month_number, accounts)
    this_income, this_spending = month_cash_flow(transactions, today.year, today.month, accounts)

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
    }

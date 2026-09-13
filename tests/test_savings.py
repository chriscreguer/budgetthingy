from datetime import date
from unittest.mock import patch

from savings import month_cash_flow, savings_since_date, savings_summary


def _transaction(day: str, amount: int, **extra) -> dict:
    line = {
        "date": day,
        "amount": amount,
        "payee_name": extra.pop("payee_name", "Merchant"),
        "transfer_account_id": extra.pop("transfer_account_id", None),
        "deleted": extra.pop("deleted", False),
        "subtransactions": extra.pop("subtransactions", []),
    }
    line.update(extra)
    return line


def test_month_cash_flow_splits_income_and_spending():
    transactions = [
        _transaction("2026-08-01", 3_000_000, payee_name="Employer"),
        _transaction("2026-08-05", -40_000),
        _transaction("2026-08-19", -60_000),
    ]

    income, spending = month_cash_flow(transactions, 2026, 8)

    assert income == 3000.0
    assert spending == 100.0


def test_month_cash_flow_ignores_other_months():
    transactions = [
        _transaction("2026-07-31", 500_000, payee_name="Employer"),
        _transaction("2026-08-05", -40_000),
        _transaction("2026-09-01", -900_000),
    ]

    assert month_cash_flow(transactions, 2026, 8) == (0.0, 40.0)


def test_month_cash_flow_skips_transfers_and_deleted_rows():
    transactions = [
        _transaction("2026-08-02", 2_000_000, payee_name="Employer"),
        # A credit card payment lands as a transfer on both sides. Counting it
        # would inflate income and spending at the same time.
        _transaction("2026-08-03", -900_000, transfer_account_id="acct-card"),
        _transaction("2026-08-03", 900_000, transfer_account_id="acct-checking"),
        _transaction("2026-08-04", -50_000, deleted=True),
        _transaction("2026-08-05", -25_000),
    ]

    assert month_cash_flow(transactions, 2026, 8) == (2000.0, 25.0)


def test_month_cash_flow_skips_excluded_payee_patterns():
    transactions = [
        _transaction("2026-08-05", -40_000, payee_name="ATM Withdrawal"),
        _transaction("2026-08-06", -10_000, payee_name="Coffee"),
    ]

    with patch("savings.config.EXCLUDED_PAYEE_PATTERNS", ("withdrawal",)):
        assert month_cash_flow(transactions, 2026, 8) == (0.0, 10.0)


def test_month_cash_flow_counts_parent_amount_for_splits():
    # YNAB parent amount already equals the sum of its subtransactions, so the
    # parent alone is the correct cash-flow figure.
    transactions = [
        _transaction(
            "2026-08-05",
            -75_000,
            subtransactions=[
                {"amount": -50_000, "deleted": False},
                {"amount": -25_000, "deleted": False},
            ],
        ),
    ]

    assert month_cash_flow(transactions, 2026, 8) == (0.0, 75.0)


def test_savings_summary_reports_last_month_savings():
    transactions = [
        _transaction("2026-08-01", 4_000_000, payee_name="Employer"),
        _transaction("2026-08-10", -1_500_000),
        _transaction("2026-09-02", -100_000),
    ]

    summary = savings_summary(transactions, today=date(2026, 9, 10))

    assert summary["last_month"]["month"] == "2026-08"
    assert summary["last_month"]["income"] == 4000.0
    assert summary["last_month"]["spending"] == 1500.0
    assert summary["saved_last_month"] == 2500.0


def test_saved_last_month_never_goes_below_zero():
    transactions = [
        _transaction("2026-08-01", 1_000_000, payee_name="Employer"),
        _transaction("2026-08-10", -1_800_000),
    ]

    summary = savings_summary(transactions, today=date(2026, 9, 10))

    assert summary["last_month"]["income"] == 1000.0
    assert summary["last_month"]["spending"] == 1800.0
    assert summary["saved_last_month"] == 0.0


def test_projected_savings_extrapolates_spending_at_current_rate():
    transactions = [
        _transaction("2026-08-01", 3_000_000, payee_name="Employer"),
        # Day 10 of 30: $500 spent so far projects to $1,500 for the month.
        _transaction("2026-09-05", -300_000),
        _transaction("2026-09-09", -200_000),
    ]

    summary = savings_summary(transactions, today=date(2026, 9, 10))

    assert summary["this_month"]["spending"] == 500.0
    assert summary["this_month"]["projected_spending"] == 1500.0
    assert summary["this_month"]["projected_income"] == 3000.0
    assert summary["projected_savings"] == 1500.0


def test_projected_savings_never_goes_below_zero():
    transactions = [
        _transaction("2026-08-01", 1_000_000, payee_name="Employer"),
        _transaction("2026-09-05", -900_000),
    ]

    summary = savings_summary(transactions, today=date(2026, 9, 10))

    assert summary["this_month"]["projected_spending"] == 2700.0
    assert summary["projected_savings"] == 0.0


def test_projected_income_falls_back_to_this_month_when_last_month_is_empty():
    transactions = [
        _transaction("2026-09-01", 2_000_000, payee_name="Employer"),
        _transaction("2026-09-05", -100_000),
    ]

    summary = savings_summary(transactions, today=date(2026, 9, 10))

    assert summary["last_month"]["income"] == 0.0
    assert summary["this_month"]["projected_income"] == 2000.0
    assert summary["projected_savings"] == 1700.0


def test_savings_summary_handles_first_day_of_month():
    transactions = [
        _transaction("2026-08-01", 3_000_000, payee_name="Employer"),
        _transaction("2026-09-01", -100_000),
    ]

    summary = savings_summary(transactions, today=date(2026, 9, 1))

    assert summary["this_month"]["projected_spending"] == 3000.0
    assert summary["projected_savings"] == 0.0


def test_savings_summary_with_no_transactions():
    summary = savings_summary([], today=date(2026, 9, 10))

    assert summary["saved_last_month"] == 0.0
    assert summary["projected_savings"] == 0.0
    assert summary["this_month"]["projected_spending"] == 0.0


def test_savings_since_date_covers_the_start_of_last_month():
    assert savings_since_date(date(2026, 9, 10)) == "2026-08-01"
    assert savings_since_date(date(2026, 1, 15)) == "2025-12-01"

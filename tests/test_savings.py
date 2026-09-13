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


CARD_ACCOUNTS = [
    {"id": "acct-card", "name": "Apple Card", "type": "creditCard"},
    {"id": "acct-checking", "name": "Share Draft", "type": "checking"},
    {"id": "acct-savings", "name": "Savings", "type": "savings"},
]


def test_card_payment_imported_as_two_plain_transactions_is_not_cash_flow():
    # The bank imports a card payment as an inflow onto the card and an outflow
    # from checking, neither flagged as a YNAB transfer. Counting them inflates
    # income and double-counts spending already recorded on the card.
    transactions = [
        _transaction("2026-08-07", 3_000_000, payee_name="External Deposit COLSA", account_id="acct-checking"),
        _transaction("2026-08-20", -80_000, payee_name="Jewel-Osco", account_id="acct-card"),
        _transaction("2026-08-03", 3_796_790, payee_name="Bill Payment", account_id="acct-card"),
        _transaction("2026-08-04", -3_796_790, payee_name="Apple Card Payment", account_id="acct-checking"),
    ]

    income, spending = month_cash_flow(transactions, 2026, 8, accounts=CARD_ACCOUNTS)

    assert income == 3000.0
    assert spending == 80.0


def test_inflow_onto_a_credit_card_is_never_income():
    # A refund lands on the card as an inflow. It is not income either way.
    transactions = [
        _transaction("2026-08-03", 45_000, payee_name="Target", account_id="acct-card"),
    ]

    assert month_cash_flow(transactions, 2026, 8, accounts=CARD_ACCOUNTS) == (0.0, 0.0)


def test_card_payment_match_survives_non_breaking_space_in_account_name():
    # The account is named "Apple Card" but the payee uses a plain space.
    transactions = [
        _transaction("2026-08-04", -500_000, payee_name="Apple Card Payment", account_id="acct-checking"),
    ]

    assert month_cash_flow(transactions, 2026, 8, accounts=CARD_ACCOUNTS) == (0.0, 0.0)


def test_ordinary_spending_from_checking_still_counts():
    transactions = [
        _transaction("2026-08-04", -120_000, payee_name="Rent", account_id="acct-checking"),
        _transaction("2026-08-05", -60_000, payee_name="Jewel-Osco", account_id="acct-card"),
    ]

    assert month_cash_flow(transactions, 2026, 8, accounts=CARD_ACCOUNTS) == (0.0, 180.0)


def test_income_into_checking_and_savings_still_counts():
    transactions = [
        _transaction("2026-08-07", 3_000_000, payee_name="Employer", account_id="acct-checking"),
        _transaction("2026-08-31", 46_840, payee_name="Interest", account_id="acct-savings"),
    ]

    income, spending = month_cash_flow(transactions, 2026, 8, accounts=CARD_ACCOUNTS)

    assert income == 3046.84
    assert spending == 0.0


def test_cash_flow_without_accounts_keeps_working():
    # Accounts are optional; without them only YNAB transfer flags are honoured.
    transactions = [
        _transaction("2026-08-07", 3_000_000, payee_name="Employer"),
        _transaction("2026-08-08", -40_000, payee_name="Coffee"),
    ]

    assert month_cash_flow(transactions, 2026, 8) == (3000.0, 40.0)


def test_savings_summary_threads_accounts_through():
    transactions = [
        _transaction("2026-08-03", 5_000_000, payee_name="Bill Payment", account_id="acct-card"),
        _transaction("2026-08-07", 3_000_000, payee_name="Employer", account_id="acct-checking"),
        _transaction("2026-08-10", -1_000_000, payee_name="Rent", account_id="acct-checking"),
    ]

    summary = savings_summary(transactions, today=date(2026, 9, 10), accounts=CARD_ACCOUNTS)

    assert summary["last_month"]["income"] == 3000.0
    assert summary["saved_last_month"] == 2000.0


def test_refund_onto_a_card_reduces_spending():
    # A merchant refund lands as an inflow on the card. It is not income, but it
    # does mean less was actually spent.
    transactions = [
        _transaction("2026-08-05", -500_000, payee_name="Guitar Center", account_id="acct-card"),
        _transaction("2026-08-20", 439_790, payee_name="Guitar Center", account_id="acct-card"),
    ]

    income, spending = month_cash_flow(transactions, 2026, 8, accounts=CARD_ACCOUNTS)

    assert income == 0.0
    assert spending == 60.21


def test_card_payment_inflow_is_not_treated_as_a_refund():
    # Payment-shaped payees must never reduce spending, or a card payoff would
    # wipe out the month's real purchases.
    for payee in ["Bill Payment", "ONLINE PAYMENT, THANK YOU", "Apple Card", "AutoPay Thank You"]:
        transactions = [
            _transaction("2026-08-05", -500_000, payee_name="Jewel-Osco", account_id="acct-card"),
            _transaction("2026-08-20", 400_000, payee_name=payee, account_id="acct-card"),
        ]

        income, spending = month_cash_flow(transactions, 2026, 8, accounts=CARD_ACCOUNTS)

        assert income == 0.0, payee
        assert spending == 500.0, payee


def test_refunds_cannot_push_spending_below_zero():
    transactions = [
        _transaction("2026-08-20", 400_000, payee_name="Guitar Center", account_id="acct-card"),
    ]

    assert month_cash_flow(transactions, 2026, 8, accounts=CARD_ACCOUNTS) == (0.0, 0.0)


def test_refund_cancels_the_purchase_in_its_original_month():
    # Speakers bought in August, returned in September. August should not be
    # punished for a purchase that was reversed.
    transactions = [
        _transaction("2026-08-10", 5_000_000, payee_name="Employer", account_id="acct-checking"),
        _transaction("2026-08-12", -800_000, payee_name="Guitar Center", account_id="acct-card"),
        _transaction("2026-09-05", 800_000, payee_name="Guitar Center", account_id="acct-card"),
    ]

    august = month_cash_flow(transactions, 2026, 8, accounts=CARD_ACCOUNTS)
    september = month_cash_flow(transactions, 2026, 9, accounts=CARD_ACCOUNTS)

    assert august == (5000.0, 0.0)
    assert september == (0.0, 0.0)


def test_partial_refund_only_cancels_part_of_the_purchase():
    transactions = [
        _transaction("2026-08-12", -800_000, payee_name="Guitar Center", account_id="acct-card"),
        _transaction("2026-09-05", -50_000, payee_name="Jewel-Osco", account_id="acct-card"),
        _transaction("2026-09-06", 439_790, payee_name="Guitar Center", account_id="acct-card"),
    ]

    assert month_cash_flow(transactions, 2026, 8, accounts=CARD_ACCOUNTS)[1] == 360.21
    assert month_cash_flow(transactions, 2026, 9, accounts=CARD_ACCOUNTS)[1] == 50.0


def test_refund_to_checking_is_not_income_and_cancels_its_purchase():
    transactions = [
        _transaction("2026-08-12", -120_000, payee_name="Target", account_id="acct-checking"),
        _transaction("2026-09-04", 120_000, payee_name="Target", account_id="acct-checking"),
    ]

    august = month_cash_flow(transactions, 2026, 8, accounts=CARD_ACCOUNTS)
    september = month_cash_flow(transactions, 2026, 9, accounts=CARD_ACCOUNTS)

    assert august == (0.0, 0.0)
    assert september == (0.0, 0.0)


def test_paycheck_is_never_mistaken_for_a_refund():
    transactions = [
        _transaction("2026-08-12", -120_000, payee_name="Target", account_id="acct-checking"),
        _transaction("2026-08-15", 3_000_000, payee_name="External Deposit COLSA", account_id="acct-checking"),
    ]

    assert month_cash_flow(transactions, 2026, 8, accounts=CARD_ACCOUNTS) == (3000.0, 120.0)


def test_refund_matches_the_most_recent_prior_purchase_from_that_payee():
    transactions = [
        _transaction("2026-08-02", -100_000, payee_name="Guitar Center", account_id="acct-card"),
        _transaction("2026-09-03", -100_000, payee_name="Guitar Center", account_id="acct-card"),
        _transaction("2026-09-10", 100_000, payee_name="Guitar Center", account_id="acct-card"),
    ]

    assert month_cash_flow(transactions, 2026, 8, accounts=CARD_ACCOUNTS)[1] == 100.0
    assert month_cash_flow(transactions, 2026, 9, accounts=CARD_ACCOUNTS)[1] == 0.0


def test_refund_with_no_matching_purchase_falls_back_to_its_own_month():
    transactions = [
        _transaction("2026-09-05", -200_000, payee_name="Jewel-Osco", account_id="acct-card"),
        _transaction("2026-09-06", 50_000, payee_name="Some Merchant", account_id="acct-card"),
    ]

    assert month_cash_flow(transactions, 2026, 9, accounts=CARD_ACCOUNTS)[1] == 150.0


def test_refund_never_attaches_to_a_later_purchase():
    # A refund cannot reverse a purchase that had not happened yet.
    transactions = [
        _transaction("2026-09-02", 100_000, payee_name="Guitar Center", account_id="acct-card"),
        _transaction("2026-09-20", -100_000, payee_name="Guitar Center", account_id="acct-card"),
    ]

    assert month_cash_flow(transactions, 2026, 9, accounts=CARD_ACCOUNTS)[1] == 0.0


def test_savings_summary_credits_last_month_for_a_refund_received_this_month():
    transactions = [
        _transaction("2026-08-01", 4_000_000, payee_name="Employer", account_id="acct-checking"),
        _transaction("2026-08-12", -900_000, payee_name="Guitar Center", account_id="acct-card"),
        _transaction("2026-09-05", 900_000, payee_name="Guitar Center", account_id="acct-card"),
    ]

    summary = savings_summary(transactions, today=date(2026, 9, 10), accounts=CARD_ACCOUNTS)

    assert summary["last_month"]["spending"] == 0.0
    assert summary["saved_last_month"] == 4000.0


def test_refund_must_land_on_the_account_that_paid():
    # Savings interest earned and credit card interest charged share a payee but
    # are unrelated money. The earned interest stays income.
    transactions = [
        _transaction("2026-08-05", -46_840, payee_name="Interest", account_id="acct-card"),
        _transaction("2026-08-31", 46_840, payee_name="Interest", account_id="acct-savings"),
    ]

    income, spending = month_cash_flow(transactions, 2026, 8, accounts=CARD_ACCOUNTS)

    assert income == 46.84
    assert spending == 46.84

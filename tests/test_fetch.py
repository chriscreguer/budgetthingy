from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from budget_pace import fetch_flexible_totals


THIS_MONTH = date.today().replace(day=2).isoformat()

MOCK_CATEGORIES_RESPONSE = {
    "data": {
        "category_groups": [
            {
                "name": "Internal Master Category",
                "categories": [
                    {"id": "internal-1", "budgeted": 0, "activity": 0},
                ],
            },
            {
                "name": "Flexible",
                "categories": [
                    {"id": "flex-1", "budgeted": 500_000, "activity": -200_000},
                    {"id": "flex-2", "budgeted": 300_000, "activity": -100_000},
                ],
            },
            {
                "name": "Quality of Life",
                "categories": [
                    {"id": "qol-1", "budgeted": 100_000, "activity": -50_000},
                    {"id": "qol-2", "budgeted": 25_000, "activity": 5_000},
                ],
            },
            {
                "name": "Fixed",
                "categories": [
                    {"id": "fixed-rent", "budgeted": 1_000_000, "activity": -1_000_000},
                ],
            },
            {
                "name": "Credit Card Payments",
                "categories": [
                    {"id": "cc-payment", "budgeted": 0, "activity": -900_000},
                ],
            },
        ]
    }
}

MOCK_TRANSACTIONS_RESPONSE = {
    "data": {
        "transactions": [
            {
                "date": THIS_MONTH,
                "amount": -40_000,
                "category_id": "flex-1",
                "transfer_account_id": None,
                "deleted": False,
                "subtransactions": [],
            },
            {
                "date": THIS_MONTH,
                "amount": -30_000,
                "category_id": "qol-1",
                "transfer_account_id": None,
                "deleted": False,
                "subtransactions": [],
            },
            {
                "date": THIS_MONTH,
                "amount": -20_000,
                "category_id": None,
                "transfer_account_id": None,
                "deleted": False,
                "subtransactions": [],
            },
            {
                "date": THIS_MONTH,
                "amount": -900_000,
                "category_id": "cc-payment",
                "transfer_account_id": None,
                "deleted": False,
                "subtransactions": [],
            },
            {
                "date": THIS_MONTH,
                "amount": -6_000_000,
                "payee_name": "Withdrawal",
                "category_id": None,
                "transfer_account_id": None,
                "deleted": False,
                "subtransactions": [],
            },
            {
                "date": THIS_MONTH,
                "amount": -1_500_000,
                "payee_name": "Credit Card Payment",
                "category_id": None,
                "transfer_account_id": "checking-account-id",
                "deleted": False,
                "subtransactions": [],
            },
            {
                "date": THIS_MONTH,
                "amount": -1_000_000,
                "category_id": "fixed-rent",
                "transfer_account_id": None,
                "deleted": False,
                "subtransactions": [],
            },
            {
                "date": THIS_MONTH,
                "amount": -50_000,
                "category_id": None,
                "transfer_account_id": None,
                "deleted": False,
                "subtransactions": [
                    {"amount": -35_000, "category_id": "flex-2", "transfer_account_id": None, "deleted": False},
                    {"amount": -15_000, "category_id": "fixed-rent", "transfer_account_id": None, "deleted": False},
                ],
            },
            {
                "date": THIS_MONTH,
                "amount": 5_000,
                "category_id": "qol-2",
                "transfer_account_id": None,
                "deleted": False,
                "subtransactions": [],
            },
        ]
    }
}


def _mock_get(response_data, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = response_data
    mock.raise_for_status = MagicMock()
    return mock


def test_sums_non_fixed_groups_only():
    # FLEXIBLE_BUDGET=0 → falls through to summing included YNAB budgeted amounts
    with patch(
        "budget_pace.requests.get",
        side_effect=[
            _mock_get(MOCK_CATEGORIES_RESPONSE),
            _mock_get(MOCK_TRANSACTIONS_RESPONSE),
        ],
    ), \
         patch("budget_pace.config.FLEXIBLE_BUDGET", 0.0), \
         patch("budget_pace.config.EXCLUDED_GROUP_NAMES", {"Fixed", "Internal Master Category", "Credit Card Payments"}), \
         patch("budget_pace.config.EXCLUDED_PAYEE_PATTERNS", ("withdrawal",)):
        assigned, spent = fetch_flexible_totals()
    # (500_000 + 300_000 + 100_000 + 25_000) / 1000 = 925.0
    assert assigned == 925.0
    # Includes categorized, uncategorized, and included split outflows.
    # Excludes fixed categories, credit-card payment categories, and transfers.
    assert spent == 125.0


def test_flexible_budget_override():
    # FLEXIBLE_BUDGET > 0 → uses configured value instead of YNAB budgeted
    with patch(
        "budget_pace.requests.get",
        side_effect=[
            _mock_get(MOCK_CATEGORIES_RESPONSE),
            _mock_get(MOCK_TRANSACTIONS_RESPONSE),
        ],
    ), \
         patch("budget_pace.config.FLEXIBLE_BUDGET", 1200.0), \
         patch("budget_pace.config.EXCLUDED_GROUP_NAMES", {"Fixed", "Internal Master Category", "Credit Card Payments"}), \
         patch("budget_pace.config.EXCLUDED_PAYEE_PATTERNS", ("withdrawal",)):
        assigned, spent = fetch_flexible_totals()
    assert assigned == 1200.0
    assert spent == 125.0


def test_uses_correct_url_and_headers():
    with patch(
        "budget_pace.requests.get",
        side_effect=[
            _mock_get(MOCK_CATEGORIES_RESPONSE),
            _mock_get(MOCK_TRANSACTIONS_RESPONSE),
        ],
    ) as mock_get, \
         patch("budget_pace.config.API_TOKEN", "tok-abc"), \
         patch("budget_pace.config.BUDGET_ID", "bud-xyz"):
        fetch_flexible_totals()
    category_call, transaction_call = mock_get.call_args_list
    assert "bud-xyz" in category_call[0][0]
    assert "bud-xyz" in transaction_call[0][0]
    assert transaction_call[1]["params"]["since_date"] == date.today().replace(day=1).isoformat()
    assert category_call[1]["headers"]["Authorization"] == "Bearer tok-abc"
    assert transaction_call[1]["headers"]["Authorization"] == "Bearer tok-abc"


def test_raises_when_no_categories_are_included():
    bad_response = {"data": {"category_groups": [{"name": "Fixed", "categories": []}]}}
    with patch("budget_pace.requests.get", return_value=_mock_get(bad_response)):
        with pytest.raises(ValueError, match="No included YNAB categories"):
            fetch_flexible_totals()


def test_raises_on_missing_api_token():
    with patch("budget_pace.config.API_TOKEN", ""):
        with pytest.raises(ValueError, match="YNAB_API_TOKEN"):
            fetch_flexible_totals()


def test_raises_on_missing_budget_id():
    with patch("budget_pace.config.BUDGET_ID", ""):
        with pytest.raises(ValueError, match="YNAB_BUDGET_ID"):
            fetch_flexible_totals()


def test_raises_on_http_error():
    mock = _mock_get({})
    mock.raise_for_status.side_effect = Exception("403 Forbidden")
    with patch("budget_pace.requests.get", return_value=mock):
        with pytest.raises(Exception, match="403"):
            fetch_flexible_totals()

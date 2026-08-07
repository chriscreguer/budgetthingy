from copy import deepcopy
from unittest.mock import patch

from budget_pace import fetch_budget_snapshot
from tests.test_fetch import MOCK_CATEGORIES_RESPONSE, MOCK_TRANSACTIONS_RESPONSE, _mock_get


def _patched_snapshot(overrides=None, transactions_response=None):
    with patch(
        "budget_pace.requests.get",
        side_effect=[
            _mock_get(MOCK_CATEGORIES_RESPONSE),
            _mock_get(transactions_response or MOCK_TRANSACTIONS_RESPONSE),
        ],
    ), \
         patch("budget_pace.config.FLEXIBLE_BUDGET", 0.0), \
         patch("budget_pace.config.EXCLUDED_GROUP_NAMES", {"Fixed", "Internal Master Category", "Credit Card Payments"}), \
         patch("budget_pace.config.EXCLUDED_PAYEE_PATTERNS", ("withdrawal",)):
        return fetch_budget_snapshot(overrides)


def test_snapshot_exposes_purchase_lines_and_category_totals():
    snapshot = _patched_snapshot()

    assert snapshot["assigned"] == 925.0
    assert snapshot["spent"] == 125.0
    assert snapshot["counts"] == {
        "included": 4,
        "excluded": 5,
        "overridden": 0,
        "total": 9,
        "clearance": {
            "total": {
                "cleared": 0,
                "uncleared": 0,
                "reconciled": 0,
                "unknown": 9,
            },
            "included": {
                "cleared": 0,
                "uncleared": 0,
                "reconciled": 0,
                "unknown": 4,
            },
        },
    }
    assert snapshot["progress"]["fill"] == snapshot["spent"] / snapshot["assigned"]
    totals = [item["spent"] for item in snapshot["category_totals"]]
    assert totals == [40.0, 35.0, 30.0, 20.0]
    assert sum(totals) == 125.0
    assert snapshot["account_totals"] == [
        {"account": "Unknown account", "spent": 125.0, "count": 4}
    ]


def test_manual_overrides_change_spending_total():
    transactions_response = deepcopy(MOCK_TRANSACTIONS_RESPONSE)
    transactions = transactions_response["data"]["transactions"]
    transactions[0]["id"] = "tx-flex"
    transactions[0]["account_name"] = "Everyday Credit Card"
    transactions[6]["id"] = "tx-fixed"
    transactions[6]["account_name"] = "Checking"

    snapshot = _patched_snapshot(
        {
            "transactions": {
                "tx-flex": {"decision": "exclude"},
                "tx-fixed": {"decision": "include"},
            }
        },
        transactions_response,
    )

    assert snapshot["spent"] == 1085.0
    assert snapshot["counts"]["overridden"] == 2
    line_by_id = {line["line_id"]: line for line in snapshot["transactions"]}
    assert line_by_id["tx-flex"]["included"] is False
    assert line_by_id["tx-fixed"]["included"] is True


def test_costco_card_account_name_is_shortened():
    transactions_response = deepcopy(MOCK_TRANSACTIONS_RESPONSE)
    transactions_response["data"]["transactions"][0]["account_name"] = (
        "Costco Anywhere Visa Card by Citi - Costco Anywhere Visa Card by Citi"
    )

    snapshot = _patched_snapshot(transactions_response=transactions_response)

    line = next(item for item in snapshot["transactions"] if item["amount"] == 40.0)
    assert line["account"] == "Costco Citi"


def test_html_entities_are_decoded_for_display():
    transactions_response = deepcopy(MOCK_TRANSACTIONS_RESPONSE)
    transaction = transactions_response["data"]["transactions"][0]
    transaction["account_name"] = "AT&amp;T Card"
    transaction["payee_name"] = "AT&amp;T"
    transaction["memo"] = "Fiber &amp; phone"

    snapshot = _patched_snapshot(transactions_response=transactions_response)

    line = next(item for item in snapshot["transactions"] if item["amount"] == 40.0)
    assert line["account"] == "AT&T Card"
    assert line["payee"] == "AT&T"
    assert line["memo"] == "Fiber & phone"


def test_snapshot_counts_uncleared_transactions():
    transactions_response = deepcopy(MOCK_TRANSACTIONS_RESPONSE)
    transactions = transactions_response["data"]["transactions"]
    transactions[0]["cleared"] = "uncleared"
    transactions[1]["cleared"] = "cleared"
    transactions[3]["cleared"] = "uncleared"

    snapshot = _patched_snapshot(transactions_response=transactions_response)

    assert snapshot["counts"]["clearance"]["included"]["uncleared"] == 1
    assert snapshot["counts"]["clearance"]["included"]["cleared"] == 1
    assert snapshot["counts"]["clearance"]["total"]["uncleared"] == 2

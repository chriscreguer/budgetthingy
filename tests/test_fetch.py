from unittest.mock import MagicMock, patch

import pytest

from budget_pace import fetch_flexible_totals


MOCK_RESPONSE = {
    "data": {
        "category_groups": [
            {
                "name": "Internal Master Category",
                "categories": [
                    {"budgeted": 0, "activity": 0},
                ],
            },
            {
                "name": "Flexible",
                "categories": [
                    {"budgeted": 500_000, "activity": -200_000},
                    {"budgeted": 300_000, "activity": -100_000},
                ],
            },
            {
                "name": "Fixed",
                "categories": [
                    {"budgeted": 1_000_000, "activity": -1_000_000},
                ],
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


def test_sums_flexible_group_only():
    # FLEXIBLE_BUDGET=0 → falls through to summing YNAB budgeted amounts
    with patch("budget_pace.requests.get", return_value=_mock_get(MOCK_RESPONSE)), \
         patch("budget_pace.config.FLEXIBLE_BUDGET", 0.0):
        assigned, spent = fetch_flexible_totals()
    # (500_000 + 300_000) / 1000 = 800.0
    assert assigned == 800.0
    # (200_000 + 100_000) / 1000 = 300.0
    assert spent == 300.0


def test_flexible_budget_override():
    # FLEXIBLE_BUDGET > 0 → uses configured value instead of YNAB budgeted
    with patch("budget_pace.requests.get", return_value=_mock_get(MOCK_RESPONSE)), \
         patch("budget_pace.config.FLEXIBLE_BUDGET", 1200.0):
        assigned, spent = fetch_flexible_totals()
    assert assigned == 1200.0
    assert spent == 300.0


def test_uses_correct_url_and_headers():
    with patch("budget_pace.requests.get", return_value=_mock_get(MOCK_RESPONSE)) as mock_get, \
         patch("budget_pace.config.API_TOKEN", "tok-abc"), \
         patch("budget_pace.config.BUDGET_ID", "bud-xyz"):
        fetch_flexible_totals()
    call_args = mock_get.call_args
    assert "bud-xyz" in call_args[0][0]
    assert call_args[1]["headers"]["Authorization"] == "Bearer tok-abc"


def test_raises_on_missing_group():
    bad_response = {"data": {"category_groups": [{"name": "Fixed", "categories": []}]}}
    with patch("budget_pace.requests.get", return_value=_mock_get(bad_response)):
        with pytest.raises(ValueError, match="not found"):
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

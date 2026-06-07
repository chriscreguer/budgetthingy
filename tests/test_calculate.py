from budget_pace import calculate_pace


def test_on_track_exact_pace():
    # Day 15 of 30, spent exactly half -> pace = 1.0 -> "On Track"
    pace, label, expected = calculate_pace(1000.0, 500.0, day=15, days_in_month=30)
    assert abs(pace - 1.0) < 0.001
    assert label == "On Track"
    assert abs(expected - 500.0) < 0.01


def test_under_budget_is_on_track():
    # Spent 10% of budget at midpoint -> pace = 0.2 -> "On Track"
    pace, label, _ = calculate_pace(1000.0, 100.0, day=15, days_in_month=30)
    assert label == "On Track"
    assert pace < 1.0


def test_over_budget_is_slow_down():
    # pace = 1.50 -> "Slow down"
    # expected = 500, spent = 750
    pace, label, _ = calculate_pace(1000.0, 750.0, day=15, days_in_month=30)
    assert label == "Slow down"


def test_zero_assigned_returns_on_track():
    # Nothing budgeted -> no pace to compute, return safe default
    pace, label, expected = calculate_pace(0.0, 0.0, day=15, days_in_month=30)
    assert pace == 0.0
    assert label == "On Track"
    assert expected == 0.0


def test_state_boundaries():
    # pace = 1.00 -> On Track
    _, label, _ = calculate_pace(1000.0, 500.0, day=15, days_in_month=30)
    assert label == "On Track"

    # pace > 1.00 -> Slow down
    _, label, _ = calculate_pace(1000.0, 501.0, day=15, days_in_month=30)
    assert label == "Slow down"

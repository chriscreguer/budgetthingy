from budget_pace import calculate_pace, progress_bar_metrics


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


def test_progress_bar_metrics_match_eink_bar_math():
    metrics = progress_bar_metrics(assigned=1000.0, spent=600.0, expected=500.0)

    assert metrics["fill"] == 0.6
    assert metrics["tick"] == 0.5
    assert metrics["on_pace_fill"] == 0.5
    assert abs(metrics["overage"] - 0.1) < 0.001


def test_progress_bar_metrics_zero_assigned():
    assert progress_bar_metrics(assigned=0.0, spent=50.0, expected=0.0) == {
        "fill": 0.0,
        "tick": 0.0,
        "on_pace_fill": 0.0,
        "overage": 0.0,
    }

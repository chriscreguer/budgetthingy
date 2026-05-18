from budget_pace import calculate_pace


def test_on_track_exact_pace():
    # Day 15 of 30, spent exactly half → pace = 1.0 → "On track"
    pace, label, expected = calculate_pace(1000.0, 500.0, day=15, days_in_month=30)
    assert abs(pace - 1.0) < 0.001
    assert label == "On track"
    assert abs(expected - 500.0) < 0.01


def test_plenty_of_room():
    # Spent 10% of budget at midpoint → pace = 0.2 → "Plenty of Room"
    pace, label, _ = calculate_pace(1000.0, 100.0, day=15, days_in_month=30)
    assert label == "Plenty of Room"
    assert pace < 0.85


def test_on_track_upper_boundary():
    # pace = 1.09 → still "On track"
    # expected = 500, so spent = 545
    pace, label, _ = calculate_pace(1000.0, 545.0, day=15, days_in_month=30)
    assert label == "On track"


def test_spend_cautiously():
    # pace = 1.20 → "Spend Cautiously"
    # expected = 500, spent = 600
    pace, label, _ = calculate_pace(1000.0, 600.0, day=15, days_in_month=30)
    assert label == "Spend Cautiously"


def test_slow_down():
    # pace = 1.50 → "Slow down"
    # expected = 500, spent = 750
    pace, label, _ = calculate_pace(1000.0, 750.0, day=15, days_in_month=30)
    assert label == "Slow down"


def test_zero_assigned_returns_on_track():
    # Nothing budgeted → no pace to compute, return safe default
    pace, label, expected = calculate_pace(0.0, 0.0, day=15, days_in_month=30)
    assert pace == 0.0
    assert label == "On track"
    assert expected == 0.0


def test_state_boundaries():
    # pace = 0.84 → Plenty of Room
    # expected = 500, spent = 420
    _, label, _ = calculate_pace(1000.0, 420.0, day=15, days_in_month=30)
    assert label == "Plenty of Room"

    # pace = 0.85 → On track
    _, label, _ = calculate_pace(1000.0, 425.0, day=15, days_in_month=30)
    assert label == "On track"

    # pace = 1.10 → Spend Cautiously
    _, label, _ = calculate_pace(1000.0, 550.0, day=15, days_in_month=30)
    assert label == "Spend Cautiously"

    # pace = 1.25 → Slow down
    _, label, _ = calculate_pace(1000.0, 625.0, day=15, days_in_month=30)
    assert label == "Slow down"

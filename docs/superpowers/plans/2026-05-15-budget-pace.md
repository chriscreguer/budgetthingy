# Budget Pace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-shot Python script that reads YNAB flexible-spending data and writes a 792×272 PNG showing budget pace state.

**Architecture:** Three pure functions — `fetch_flexible_totals` → `calculate_pace` → `render_png` — wired by `main()`. Config loaded from `.env` via python-dotenv at import time. PNG rendered with Pillow. No daemon, no watcher — cron runs it hourly.

**Tech Stack:** Python 3.11+, requests, Pillow, python-dotenv, pytest

---

## File Map

| File | Role |
|---|---|
| `config.py` | Loads `.env`, exposes `API_TOKEN`, `BUDGET_ID`, `GROUP_NAME` |
| `budget_pace.py` | All logic: fetch, calculate, render, main |
| `requirements.txt` | Pinned dependencies |
| `.env` | Credentials (existing file, updated keys) |
| `.gitignore` | Ignore `output.png`, `__pycache__`, `.env` |
| `fonts/RobotoBold.ttf` | Bundled font (binary, committed to repo) |
| `tests/conftest.py` | Sets dummy env vars before any import of config.py |
| `tests/test_calculate.py` | Unit tests for `calculate_pace` and state mapping |
| `tests/test_fetch.py` | Unit tests for `fetch_flexible_totals` (mocked HTTP) |
| `tests/test_render.py` | Tests that `render_png` creates a 792×272 PNG |

---

## Task 1: Scaffold — delete old files, create project skeleton

**Files:**
- Delete: `client/`, `server/`, `shared/`, `package.json`, `package-lock.json`
- Create: `requirements.txt`, `.gitignore`, `tests/__init__.py`, `tests/conftest.py`
- Modify: `.env`

- [ ] **Step 1: Delete the old web app**

```bash
cd /Users/chriscreguer/Downloads/budget-display
rm -rf client server shared package.json package-lock.json node_modules
```

Expected: no output, those directories are gone.

- [ ] **Step 2: Create requirements.txt**

```
requests>=2.31
Pillow>=10.0
python-dotenv>=1.0
pytest>=8.0
```

- [ ] **Step 3: Update .env with the new key names**

Replace the contents of `.env` with:

```
YNAB_API_TOKEN=
YNAB_BUDGET_ID=
FLEXIBLE_GROUP_NAME=Flexible
```

(Leave values blank for now; you'll fill them in during the smoke test.)

- [ ] **Step 4: Create .gitignore**

```
output.png
__pycache__/
*.pyc
.env
*.egg-info/
.pytest_cache/
```

- [ ] **Step 5: Create tests/__init__.py**

Empty file:

```python
```

- [ ] **Step 6: Create tests/conftest.py**

This must set env vars BEFORE any test file imports `config.py`:

```python
import os
os.environ.setdefault("YNAB_API_TOKEN", "test-token-placeholder")
os.environ.setdefault("YNAB_BUDGET_ID", "test-budget-id-placeholder")
os.environ.setdefault("FLEXIBLE_GROUP_NAME", "Flexible")
```

- [ ] **Step 7: Install dependencies**

```bash
python3 -m pip install -r requirements.txt
```

Expected: pip installs requests, Pillow, python-dotenv, pytest. Last line is something like `Successfully installed ...`.

- [ ] **Step 8: Initialize git and commit**

```bash
git init
git add requirements.txt .gitignore tests/ .env.example docs/
git commit -m "chore: scaffold budget-pace Python project"
```

---

## Task 2: config.py

**Files:**
- Create: `config.py`

- [ ] **Step 1: Create config.py**

```python
from dotenv import load_dotenv
import os

load_dotenv()

API_TOKEN: str = os.environ.get("YNAB_API_TOKEN", "")
BUDGET_ID: str = os.environ.get("YNAB_BUDGET_ID", "")
GROUP_NAME: str = os.environ.get("FLEXIBLE_GROUP_NAME", "Flexible")
```

No fail-fast at import time — credentials are validated inside `fetch_flexible_totals()` when they're actually used. This keeps tests simple.

- [ ] **Step 2: Verify it imports cleanly**

```bash
python3 -c "import config; print(config.GROUP_NAME)"
```

Expected output:
```
Flexible
```

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat: add config.py with dotenv loading"
```

---

## Task 3: Calculation logic (TDD)

**Files:**
- Create: `budget_pace.py` (initial skeleton + `calculate_pace`)
- Create: `tests/test_calculate.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_calculate.py`:

```python
from budget_pace import calculate_pace


def test_on_track_exact_pace():
    # Day 15 of 30, spent exactly half → pace = 1.0 → "On Track"
    pace, label, expected = calculate_pace(1000.0, 500.0, day=15, days_in_month=30)
    assert abs(pace - 1.0) < 0.001
    assert label == "On Track"
    assert abs(expected - 500.0) < 0.01


def test_plenty_of_room():
    # Spent 10% of budget at midpoint → pace = 0.2 → "Plenty of Room"
    pace, label, _ = calculate_pace(1000.0, 100.0, day=15, days_in_month=30)
    assert label == "Plenty of Room"
    assert pace < 0.85


def test_on_track_upper_boundary():
    # pace = 1.09 → still "On Track"
    # expected = 500, so spent = 545
    pace, label, _ = calculate_pace(1000.0, 545.0, day=15, days_in_month=30)
    assert label == "On Track"


def test_spend_cautiously():
    # pace = 1.20 → "Spend Cautiously"
    # expected = 500, spent = 600
    pace, label, _ = calculate_pace(1000.0, 600.0, day=15, days_in_month=30)
    assert label == "Spend Cautiously"


def test_slow_down():
    # pace = 1.50 → "Slow Down"
    # expected = 500, spent = 750
    pace, label, _ = calculate_pace(1000.0, 750.0, day=15, days_in_month=30)
    assert label == "Slow Down"


def test_zero_assigned_returns_on_track():
    # Nothing budgeted → no pace to compute, return safe default
    pace, label, expected = calculate_pace(0.0, 0.0, day=15, days_in_month=30)
    assert pace == 0.0
    assert label == "On Track"
    assert expected == 0.0


def test_state_boundaries():
    # pace = 0.84 → Plenty of Room
    # expected = 500, spent = 420
    _, label, _ = calculate_pace(1000.0, 420.0, day=15, days_in_month=30)
    assert label == "Plenty of Room"

    # pace = 0.85 → On Track
    _, label, _ = calculate_pace(1000.0, 425.0, day=15, days_in_month=30)
    assert label == "On Track"

    # pace = 1.10 → Spend Cautiously
    _, label, _ = calculate_pace(1000.0, 550.0, day=15, days_in_month=30)
    assert label == "Spend Cautiously"

    # pace = 1.25 → Slow Down
    _, label, _ = calculate_pace(1000.0, 625.0, day=15, days_in_month=30)
    assert label == "Slow Down"
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/test_calculate.py -v
```

Expected: `ImportError: cannot import name 'calculate_pace' from 'budget_pace'` (or ModuleNotFoundError if file doesn't exist yet). This confirms the test is wired correctly.

- [ ] **Step 3: Create budget_pace.py with calculate_pace**

```python
import calendar
import sys
from datetime import date

import requests

import config


def fetch_flexible_totals() -> tuple[float, float]:
    raise NotImplementedError


def calculate_pace(
    assigned: float,
    spent: float,
    day: int | None = None,
    days_in_month: int | None = None,
) -> tuple[float, str, float]:
    """Returns (pace_ratio, state_label, expected_dollars)."""
    today = date.today()
    if day is None:
        day = today.day
    if days_in_month is None:
        days_in_month = calendar.monthrange(today.year, today.month)[1]

    if assigned == 0:
        return 0.0, "On Track", 0.0

    expected = assigned * (day / days_in_month)
    pace = spent / expected if expected > 0 else 0.0

    if pace < 0.85:
        label = "Plenty of Room"
    elif pace < 1.10:
        label = "On Track"
    elif pace < 1.25:
        label = "Spend Cautiously"
    else:
        label = "Slow Down"

    return pace, label, expected


def render_png(
    assigned: float,
    spent: float,
    expected: float,
    pace_ratio: float,
    state_label: str,
    output_path: str = "output.png",
) -> None:
    raise NotImplementedError


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests — expect all to pass**

```bash
pytest tests/test_calculate.py -v
```

Expected:
```
PASSED tests/test_calculate.py::test_on_track_exact_pace
PASSED tests/test_calculate.py::test_plenty_of_room
PASSED tests/test_calculate.py::test_on_track_upper_boundary
PASSED tests/test_calculate.py::test_spend_cautiously
PASSED tests/test_calculate.py::test_slow_down
PASSED tests/test_calculate.py::test_zero_assigned_returns_on_track
PASSED tests/test_calculate.py::test_state_boundaries
7 passed in 0.XXs
```

- [ ] **Step 5: Commit**

```bash
git add budget_pace.py tests/test_calculate.py
git commit -m "feat: add calculate_pace with state mapping (TDD)"
```

---

## Task 4: YNAB fetch (TDD with mocked HTTP)

**Files:**
- Modify: `budget_pace.py` — implement `fetch_flexible_totals`
- Create: `tests/test_fetch.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fetch.py`:

```python
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
    with patch("budget_pace.requests.get", return_value=_mock_get(MOCK_RESPONSE)):
        assigned, spent = fetch_flexible_totals()
    # (500_000 + 300_000) / 1000 = 800.0
    assert assigned == 800.0
    # (200_000 + 100_000) / 1000 = 300.0
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
```

- [ ] **Step 2: Run tests — expect NotImplementedError**

```bash
pytest tests/test_fetch.py -v
```

Expected: all tests fail with `NotImplementedError`.

- [ ] **Step 3: Implement fetch_flexible_totals in budget_pace.py**

Replace the `fetch_flexible_totals` stub:

```python
def fetch_flexible_totals() -> tuple[float, float]:
    """Returns (assigned_dollars, spent_dollars) for the Flexible category group."""
    if not config.API_TOKEN:
        raise ValueError("YNAB_API_TOKEN is not set in environment or .env")
    if not config.BUDGET_ID:
        raise ValueError("YNAB_BUDGET_ID is not set in environment or .env")

    url = f"https://api.ynab.com/v1/budgets/{config.BUDGET_ID}/categories"
    headers = {"Authorization": f"Bearer {config.API_TOKEN}"}

    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()

    groups = resp.json()["data"]["category_groups"]
    for group in groups:
        if group["name"] == config.GROUP_NAME:
            cats = group["categories"]
            assigned = sum(c["budgeted"] for c in cats) / 1000
            spent = sum(-c["activity"] for c in cats) / 1000
            return assigned, spent

    raise ValueError(
        f"Category group '{config.GROUP_NAME}' not found in budget. "
        "Check FLEXIBLE_GROUP_NAME in .env."
    )
```

- [ ] **Step 4: Run all tests — expect all to pass**

```bash
pytest tests/ -v
```

Expected:
```
PASSED tests/test_calculate.py::test_on_track_exact_pace
...
PASSED tests/test_fetch.py::test_sums_flexible_group_only
PASSED tests/test_fetch.py::test_uses_correct_url_and_headers
PASSED tests/test_fetch.py::test_raises_on_missing_group
PASSED tests/test_fetch.py::test_raises_on_missing_api_token
PASSED tests/test_fetch.py::test_raises_on_missing_budget_id
PASSED tests/test_fetch.py::test_raises_on_http_error
13 passed in 0.XXs
```

- [ ] **Step 5: Commit**

```bash
git add budget_pace.py tests/test_fetch.py
git commit -m "feat: implement fetch_flexible_totals with YNAB API (TDD)"
```

---

## Task 5: Font and PNG render (TDD)

**Files:**
- Create: `fonts/RobotoBold.ttf` (downloaded)
- Modify: `budget_pace.py` — implement `render_png`
- Create: `tests/test_render.py`

- [ ] **Step 1: Write the failing render tests**

Create `tests/test_render.py`:

```python
import os
import pytest
from PIL import Image

from budget_pace import render_png


def test_creates_file(tmp_path):
    out = str(tmp_path / "out.png")
    render_png(
        assigned=1800.0,
        spent=720.0,
        expected=900.0,
        pace_ratio=0.8,
        state_label="Plenty of Room",
        output_path=out,
    )
    assert os.path.exists(out)


def test_dimensions(tmp_path):
    out = str(tmp_path / "out.png")
    render_png(
        assigned=1800.0,
        spent=720.0,
        expected=900.0,
        pace_ratio=0.8,
        state_label="Plenty of Room",
        output_path=out,
    )
    img = Image.open(out)
    assert img.size == (792, 272)


def test_slow_down_state(tmp_path):
    # Just verify it doesn't raise for the most alarming state
    out = str(tmp_path / "out.png")
    render_png(
        assigned=1800.0,
        spent=2000.0,
        expected=900.0,
        pace_ratio=2.22,
        state_label="Slow Down",
        output_path=out,
    )
    assert os.path.exists(out)


def test_zero_assigned(tmp_path):
    # Assigned = 0 edge case should not raise
    out = str(tmp_path / "out.png")
    render_png(
        assigned=0.0,
        spent=0.0,
        expected=0.0,
        pace_ratio=0.0,
        state_label="On Track",
        output_path=out,
    )
    assert os.path.exists(out)
```

- [ ] **Step 2: Run tests — expect NotImplementedError**

```bash
pytest tests/test_render.py -v
```

Expected: all 4 tests fail with `NotImplementedError`.

- [ ] **Step 3: Download Roboto Bold font**

```bash
mkdir -p fonts
curl -L -o fonts/RobotoBold.ttf \
  "https://raw.githubusercontent.com/google/fonts/main/apache/roboto/static/Roboto-Bold.ttf"
```

Expected: `fonts/RobotoBold.ttf` is created, ~130KB.

Verify:
```bash
ls -lh fonts/RobotoBold.ttf
```

Expected: file exists, size ~130K.

- [ ] **Step 4: Implement render_png in budget_pace.py**

Add these constants near the top of `budget_pace.py`, after the imports:

```python
_WIDTH = 792
_HEIGHT = 272
_HALF = _HEIGHT // 2
_PAD = 40
_BAR_H = 30
_BAR_TOP = _HALF + 36
_FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "RobotoBold.ttf")
```

Add `import os` to the imports at the top of `budget_pace.py`.

Replace the `render_png` stub with:

```python
def render_png(
    assigned: float,
    spent: float,
    expected: float,
    pace_ratio: float,
    state_label: str,
    output_path: str = "output.png",
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("L", (_WIDTH, _HEIGHT), color=255)
    draw = ImageDraw.Draw(img)

    # --- Top half: auto-scaled state label ---
    max_w = _WIDTH - 2 * _PAD
    max_h = _HALF - 20
    font = _fit_font(draw, state_label, max_w, max_h)
    bb = draw.textbbox((0, 0), state_label, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    tx = (_WIDTH - tw) // 2 - bb[0]
    ty = (_HALF - th) // 2 - bb[1]
    draw.text((tx, ty), state_label, fill=0, font=font)

    # --- Bottom half: progress bar ---
    bar_left = _PAD
    bar_right = _WIDTH - _PAD
    bar_width = bar_right - bar_left

    draw.rectangle(
        [bar_left, _BAR_TOP, bar_right, _BAR_TOP + _BAR_H],
        outline=0,
        width=2,
    )

    if assigned > 0:
        fill_frac = min(spent / assigned, 1.0)
        fill_right = bar_left + int(fill_frac * bar_width)
        if fill_right > bar_left:
            draw.rectangle(
                [bar_left, _BAR_TOP, fill_right, _BAR_TOP + _BAR_H],
                fill=0,
            )

        tick_frac = min(expected / assigned, 1.0)
        tick_x = bar_left + int(tick_frac * bar_width)
        draw.rectangle(
            [tick_x - 2, _BAR_TOP - 6, tick_x + 2, _BAR_TOP + _BAR_H + 6],
            fill=0,
        )

    small_font = ImageFont.truetype(_FONT_PATH, 18)
    label_text = f"${spent:,.0f} of ${assigned:,.0f}"
    bb2 = draw.textbbox((0, 0), label_text, font=small_font)
    lw = bb2[2] - bb2[0]
    lx = (_WIDTH - lw) // 2 - bb2[0]
    ly = _BAR_TOP + _BAR_H + 10
    draw.text((lx, ly), label_text, fill=0, font=small_font)

    img.save(output_path)
```

Add the `_fit_font` helper just above `render_png`:

```python
def _fit_font(draw, text: str, max_w: int, max_h: int, max_size: int = 120):
    from PIL import ImageFont
    for size in range(max_size, 8, -2):
        font = ImageFont.truetype(_FONT_PATH, size)
        bb = draw.textbbox((0, 0), text, font=font)
        if (bb[2] - bb[0]) <= max_w and (bb[3] - bb[1]) <= max_h:
            return font
    return ImageFont.truetype(_FONT_PATH, 10)
```

- [ ] **Step 5: Run all tests — expect all to pass**

```bash
pytest tests/ -v
```

Expected:
```
PASSED tests/test_calculate.py::...  (7 tests)
PASSED tests/test_fetch.py::...      (6 tests)
PASSED tests/test_render.py::test_creates_file
PASSED tests/test_render.py::test_dimensions
PASSED tests/test_render.py::test_slow_down_state
PASSED tests/test_render.py::test_zero_assigned
17 passed in X.XXs
```

- [ ] **Step 6: Commit**

```bash
git add fonts/RobotoBold.ttf budget_pace.py tests/test_render.py
git commit -m "feat: implement render_png with Pillow (TDD)"
```

---

## Task 6: Wire up main() and final integration

**Files:**
- Modify: `budget_pace.py` — implement `main()`

- [ ] **Step 1: Replace the main() stub**

```python
def main() -> None:
    try:
        assigned, spent = fetch_flexible_totals()
        pace_ratio, state_label, expected = calculate_pace(assigned, spent)
        render_png(assigned, spent, expected, pace_ratio, state_label)
        print(
            f"{state_label} | pace={pace_ratio:.2f} "
            f"| ${spent:,.0f} of ${assigned:,.0f} "
            f"(expected ${expected:,.0f})"
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 2: Run all tests one final time**

```bash
pytest tests/ -v
```

Expected: 17 passed, 0 failed.

- [ ] **Step 3: Commit**

```bash
git add budget_pace.py
git commit -m "feat: wire main() — budget-pace script complete"
```

---

## Task 7: Smoke test with real YNAB credentials

- [ ] **Step 1: Fill in .env**

Edit `.env`:
```
YNAB_API_TOKEN=<your token here>
YNAB_BUDGET_ID=<your budget ID here>
FLEXIBLE_GROUP_NAME=Flexible
```

To find your budget ID: `curl -s -H "Authorization: Bearer <token>" https://api.ynab.com/v1/budgets | python3 -m json.tool | grep '"id"'` — the first ID is your default budget.

- [ ] **Step 2: Run the script**

```bash
python3 budget_pace.py
```

Expected: one line printed, e.g.:
```
On Track | pace=0.97 | $842 of $1,800 (expected $869)
```

And `output.png` created in the current directory.

- [ ] **Step 3: Inspect the PNG**

```bash
open output.png
```

Verify:
- 792×272 pixels
- State label fills the top half legibly
- Progress bar in the bottom half with a tick mark
- Dollar label below the bar

- [ ] **Step 4: Test a failure path**

Temporarily set `FLEXIBLE_GROUP_NAME=DoesNotExist` in `.env`, run again:

```bash
python3 budget_pace.py
echo "Exit code: $?"
```

Expected:
```
ERROR: Category group 'DoesNotExist' not found in budget. Check FLEXIBLE_GROUP_NAME in .env.
Exit code: 1
```

Restore `FLEXIBLE_GROUP_NAME=Flexible`.

- [ ] **Step 5: Set up hourly cron (optional)**

```bash
crontab -e
```

Add:
```
0 * * * * cd /Users/chriscreguer/Downloads/budget-display && python3 budget_pace.py >> /tmp/budget-pace.log 2>&1
```

---

## Self-Review

**Spec coverage:**
- [x] Connect to YNAB API → `fetch_flexible_totals` (Task 4)
- [x] Find "Flexible" category group by name → scans `category_groups` by `name`
- [x] Sum assigned and spent (activity flipped) → milliunits ÷ 1000
- [x] Calculate expected pace → `calculate_pace` (Task 3)
- [x] Map pace ratio to four states → boundary tests in `test_calculate.py`
- [x] 792×272 PNG output → `render_png` asserts in `test_render.py`
- [x] Top half: state text large and centered → `_fit_font` + centering math
- [x] Bottom half: progress bar + tick → `render_png` bar section
- [x] `assigned == 0` edge case → `test_zero_assigned_returns_on_track`, `test_zero_assigned`
- [x] Exit code 1 on error → `main()` calls `sys.exit(1)`
- [x] `FLEXIBLE_GROUP_NAME` not found → `test_raises_on_missing_group`
- [x] python-dotenv config → Task 2

**Type consistency:**
- `calculate_pace` returns `(float, str, float)` — matches all callers
- `render_png` signature is `(assigned, spent, expected, pace_ratio, state_label, output_path)` — matches all call sites
- `fetch_flexible_totals` returns `(float, float)` — matches `main()`

**No placeholders:** confirmed.

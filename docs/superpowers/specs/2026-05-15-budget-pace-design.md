# Budget Pace — Design Spec
_2026-05-15_

## Goal
A one-shot Python script that reads YNAB data and writes a 792×272 PNG showing whether the user is spending too fast against their monthly flexible-spending pace. Intended for a Waveshare 5.79" 4-color e-ink panel, refreshed hourly via cron.

## Files (at budget-display/ root)
```
budget_pace.py      # entry point
config.py           # loads .env, exposes constants
requirements.txt    # requests, Pillow, python-dotenv
.env                # YNAB_API_TOKEN, YNAB_BUDGET_ID, FLEXIBLE_GROUP_NAME
output.png          # written on every run
```

Old React/TypeScript web app files are deleted.

## Configuration
`config.py` calls `load_dotenv()` at import time, then exposes:
- `API_TOKEN` — from `YNAB_API_TOKEN`
- `BUDGET_ID` — from `YNAB_BUDGET_ID`
- `GROUP_NAME` — from `FLEXIBLE_GROUP_NAME`, defaults to `"Flexible"`

Raises `ValueError` at import if `API_TOKEN` or `BUDGET_ID` are missing.

## Data flow

### 1. Fetch (`fetch_flexible_totals`)
```
GET https://api.ynab.com/v1/budgets/{BUDGET_ID}/categories
Authorization: Bearer {API_TOKEN}
```
Scan response for the group matching `GROUP_NAME`. Sum across its `categories`:
```python
assigned = sum(cat["budgeted"] for cat in group["categories"]) / 1000
spent    = sum(-cat["activity"] for cat in group["categories"]) / 1000
```
YNAB amounts are milliunits (1000 = $1.00).

Raises `ValueError("Flexible group not found")` if group is absent.
Raises `requests.HTTPError` on non-2xx response.

### 2. Calculate (`calculate_pace`)
```python
days_elapsed  = today.day
days_in_month = calendar.monthrange(today.year, today.month)[1]
expected      = assigned * (days_elapsed / days_in_month)
pace          = spent / expected
```
Returns `(pace_ratio, state_label, expected)`.

Edge cases:
- `assigned == 0` → return `(0.0, "On Track", 0.0)`
- `expected == 0` → same fallback

### 3. State mapping
| pace | label |
|---|---|
| < 0.85 | Plenty of Room |
| 0.85 – 1.10 | On Track |
| 1.10 – 1.25 | Spend Cautiously |
| ≥ 1.25 | Slow Down |

### 4. Render (`render_png`)
Canvas: 792×272 px, white background, black ink.

**Top half (136px):** state label, centered, auto-scaled bold font (Roboto Bold TTF bundled), capped to fit.

**Bottom half (136px):**
- Progress bar track: black outline rectangle, 40px horizontal padding
- Fill: solid black from left to `min(spent/assigned, 1.0)`
- Tick: vertical black line at `min(expected/assigned, 1.0)` position
- Label below bar: `$spent of $assigned` in small type

Output written to `output.png` in the working directory.

### 5. main()
Calls fetch → calculate → render. On any exception: prints error to stderr, exits with code 1 so cron notices.

## Dependencies
```
requests>=2.31
Pillow>=10.0
python-dotenv>=1.0
```

## Out of scope
- Daemon mode, file watching, live reload
- Color per state (all black for now; tunable later)
- Network retry logic (single attempt; cron retries on next tick)

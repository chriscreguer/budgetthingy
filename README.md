# Budget Display

Server-rendered budget pace image for a Waveshare 5.79" e-paper display.

The ESP32 fetches one binary frame from Vercel:

```text
https://budgetthingy.vercel.app/api/display
```

That request does the whole job:

1. Fetch non-fixed spending totals from YNAB.
2. Render the 792x272 image with Pillow.
3. Convert it to the 53,856-byte e-paper buffer.
4. Return those bytes directly to the ESP32.

There is no Vercel Blob store in the request path.

## Vercel Environment Variables

Set these on the Vercel project:

```text
YNAB_API_TOKEN=...
YNAB_BUDGET_ID=...
FIXED_GROUP_NAME=Fixed
```

Optional:

```text
EXCLUDED_GROUP_NAMES=Fixed,Internal Master Category,Credit Card Payments
EXCLUDED_PAYEE_PATTERNS=Withdrawal
FLEXIBLE_BUDGET=0
DASHBOARD_KEY=...
UPSTASH_REDIS_REST_URL=...
UPSTASH_REDIS_REST_TOKEN=...
BUDGET_DASHBOARD_STORE_KEY=budget-display:transaction-overrides
```

By default, the display counts every visible YNAB category group except `Fixed`, `Internal Master Category`, and `Credit Card Payments`. Set `EXCLUDED_GROUP_NAMES` if your fixed-cost group has a different name or you want to exclude more groups.

Use `EXCLUDED_PAYEE_PATTERNS` for bank/card movement that YNAB imports as a normal transaction instead of a transfer. Matching is case-insensitive substring matching, so `Withdrawal` excludes payees like `Withdrawal`.

When `FLEXIBLE_BUDGET` is greater than zero, that fixed amount is used instead of summing the included YNAB budgeted amounts.

## Endpoints

```text
GET /api/display
```

Returns `application/octet-stream`, exactly 53,856 bytes, for the firmware.

```text
GET /api/generate
```

Returns JSON metadata for debugging the same generated frame:

```json
{"ok": true, "path": "budget.bin", "bytes": 53856}
```

## Local Dashboard

Run the dashboard on your computer:

```bash
python dashboard.py
```

Then open:

```text
http://127.0.0.1:8765
```

The dashboard fetches current-month YNAB purchases, shows account/card totals,
shows the detailed pace math, and lets you set each purchase to Auto, Include,
or Exclude. Manual decisions are saved locally in:

```text
data/transaction_overrides.json
```

The purchase table includes current-month YNAB outflows across all accounts.
Deleted transactions, inflows, and zero/positive lines are omitted. The pace total
counts rows marked Included. By default, rows can be Excluded because of transfer
status, configured excluded category groups, or configured excluded payee patterns;
the table shows the reason and a manual Include/Exclude decision overrides it.

The dashboard also serves an override-aware frame at:

```text
http://<your-computer-ip>:8765/api/display
```

`Reprint Now` regenerates `budget.bin` and `output_byr.png` using the dashboard
overrides and increments a local reprint token. The local dashboard also exposes:

```text
http://<your-computer-ip>:8765/api/reprint-token
```

The checked-in ESP32 firmware points at the hosted Vercel display endpoint. To
test the physical board against this local dashboard, change `IMAGE_URL` in
`firmware/budget_pace/budget_pace.ino` to the local `/api/display` URL and flash
the ESP32 again.

## Hosted Dashboard

The same dashboard is served by Vercel at:

```text
https://budgetthingy.vercel.app/
```

Set `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` in Vercel to make
manual Include/Exclude decisions persistent across requests and deployments.
Without those variables, Vercel functions cannot keep dashboard edits.

Set `DASHBOARD_KEY` in Vercel to protect transaction details. Open the hosted
dashboard as:

```text
https://budgetthingy.vercel.app/?key=<DASHBOARD_KEY>
```

The ESP32 firmware fetches frames from:

```text
https://budgetthingy.vercel.app/api/display
```

The checked-in firmware wakes at 9:00 AM and 5:00 PM Central, refreshes the
e-paper panel from the hosted dashboard, then puts the ESP32 into deep sleep
until the next scheduled wake. Dashboard edits apply at the next scheduled wake
or the next time the board is power-cycled. `Reprint Now` updates the server-side
frame/token, but it cannot wake a sleeping ESP32 on demand.

After that hosted firmware is flashed, the display only needs power and Wi-Fi;
the Mac dashboard server does not need to be running.

## Local Checks

```bash
python -m pytest -q
python -m py_compile api/index.py api/generate.py api/display.py dashboard.py
```

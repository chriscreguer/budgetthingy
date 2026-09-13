# Budget Display

Server-rendered budget pace image for a Waveshare 5.79" e-paper display.

The ESP32 fetches one binary frame from Vercel:

```text
https://budgetthingy.vercel.app/api/display
```

That request does the whole job:

1. Fetch current-month spending totals from YNAB.
2. Render the 792x272 image with Pillow.
3. Convert it to the 53,856-byte e-paper buffer.
4. Return those bytes directly to the ESP32.

There is no Vercel Blob store in the request path.

## Vercel Environment Variables

Set these on the Vercel project:

```text
YNAB_API_TOKEN=...
YNAB_BUDGET_ID=...
```

Optional:

```text
EXCLUDED_PAYEE_PATTERNS=Withdrawal
FLEXIBLE_BUDGET=0
DASHBOARD_KEY=...
UPSTASH_REDIS_REST_URL=...
UPSTASH_REDIS_REST_TOKEN=...
BUDGET_DASHBOARD_STORE_KEY=budget-display:transaction-overrides
```

By default, the display counts current-month YNAB outflows across every category group, including uncategorized transactions. Category data is used for labels and, when `FLEXIBLE_BUDGET=0`, to derive the default assigned amount.

Use `EXCLUDED_PAYEE_PATTERNS` for bank/card movement that YNAB imports as a normal transaction instead of a transfer. Matching is case-insensitive substring matching, so `Withdrawal` excludes payees like `Withdrawal`.

The monthly budget is resolved in this order:

1. The budget set in the dashboard (stored in the app store, shared by the local
   and hosted dashboards).
2. `FLEXIBLE_BUDGET`, when greater than zero.
3. The sum of visible YNAB budgeted amounts.

Editing the budget in the dashboard writes to the app store, so it survives
restarts and applies to the e-paper frame at the next wake. `FLEXIBLE_BUDGET`
remains the fallback for a fresh instance with nothing saved.

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

```text
POST /api/budget?key=<DASHBOARD_KEY>
```

Sets the monthly budget and returns the refreshed dashboard payload. Expected
JSON:

```json
{"monthly": 2000}
```

Zero clears the app budget and falls back to `FLEXIBLE_BUDGET`, then to YNAB
budgeted totals. Negative or non-numeric amounts return `400`.

```text
POST /api/provisional-transaction?key=<DASHBOARD_KEY>
```

Stores an Apple Wallet/Citi alert transaction in the app store so the dashboard
and e-paper frame count it immediately. Expected JSON:

```json
{
  "source": "apple_wallet",
  "merchant": "Target",
  "amount": "42.19",
  "card": "Apple Card",
  "occurred_at": "2026-08-27T17:12:00-05:00"
}
```

The app keeps the raw payload, normalizes the amount to milliunits, and hides the
provisional row from spending totals once a matching YNAB transaction appears.

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

The `Assigned` tile is editable: click `Edit`, type a new monthly budget, and
press Enter (Escape cancels).

Two savings tiles sit beside it:

- **Saved Last Month** - last month's income minus last month's spending,
  floored at zero.
- **Projected Savings** - last month's income minus this month's spending
  extrapolated from the run rate so far, floored at zero.

Both figures come straight from YNAB and deliberately ignore manual
Include/Exclude overrides.

Credit card payments are the main thing that would corrupt them, and they arrive
two ways. Linked YNAB transfers are skipped by their transfer flag. Payments the
bank imports as two ordinary transactions are caught using account types from
`/v1/budgets/{id}/accounts`:

- Money landing on a `creditCard` account is never income. It is a payoff when
  the payee names the card or reads like a payment (`payment`, `thank you`,
  `autopay`, `bill pay`), and otherwise a refund.
- An outflow whose payee names one of those card accounts is a card payoff, not
  spending, because the purchases were already counted on the card itself.

Account-name matching normalizes whitespace, since YNAB stores names like
`Apple<nbsp>Card` with a non-breaking space that plain matching misses.

A refund is booked against the month of the purchase it reverses, not the month
it arrives, so buying something in one month and returning it the next nets to
zero instead of making the month of the purchase look worse. A refund matches a
purchase on the same account, with the same payee, made within
`REFUND_MATCH_DAYS` (120) before it, most recent first, and can span several
purchases. Requiring the same account keeps unrelated money with a colliding
payee apart, such as savings interest earned and credit card interest charged.
An inflow to a checking or savings account that matches a purchase this way is a
debit card return, so it reduces spending rather than counting as income.
Anything left unmatched falls back to the month the refund arrived, which is the
best available answer when the purchase predates the fetched window.

Income is taken from last month rather than extrapolated, because paychecks
arrive in lumps and a day-of-month projection swings wildly. Projected spending
is a straight linear run rate, so it reads high early in a month whose fixed
costs have not posted yet.

The purchase table includes current-month YNAB outflows across all accounts and category states.
Deleted transactions, inflows, and zero/positive lines are omitted. The pace total
counts rows marked Included. By default, rows can be Excluded because of transfer
status or configured excluded payee patterns; the table shows the reason and a
manual Include/Exclude decision overrides it.

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

## Future Transaction Sources

See [docs/provisional-transactions.md](docs/provisional-transactions.md) for the
Apple Wallet/Citi alert path for provisional pending transactions, including
webhook.site testing, app endpoint design, reconciliation with YNAB, and the
future smart plug trigger.

## Local Checks

```bash
python -m pytest -q
python -m py_compile api/index.py api/generate.py api/display.py dashboard.py savings.py
```

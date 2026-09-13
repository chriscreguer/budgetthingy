# Provisional Transactions Plan

This project currently builds the e-paper progress bar from YNAB transactions.
YNAB does not expose pending transactions through its API, and SimpleFIN is not
fresh enough for reliable same-day Apple Card visibility.

The app now includes a provisional transaction path for real-time-ish events.

## Implemented Flow

Use iPhone Shortcuts to send Apple Wallet transaction events into the budget app.

Flow:

```text
iPhone Wallet transaction automation
-> POST JSON to this app
-> store provisional transaction
-> budget snapshot includes YNAB rows plus provisional rows
-> e-paper frame uses combined spending
```

Before adding app code, test the Shortcut with `https://webhook.site/` and save
one real redacted payload. That payload determines the exact parser this app
should accept.

## App Endpoint

Use:

```text
POST /api/provisional-transaction?key=<DASHBOARD_KEY>
```

Expected JSON shape, adjusted after the webhook.site test:

```json
{
  "source": "apple_wallet",
  "merchant": "Target",
  "amount": "42.19",
  "card": "Apple Card",
  "occurred_at": "2026-08-27T17:12:00-05:00"
}
```

Implementation notes:

- Authenticate with the existing `DASHBOARD_KEY` check.
- Store rows in the existing local/Upstash store, next to transaction overrides.
- Store provisional rows under `provisional_transactions`.
- Preserve the original raw payload for debugging.
- Convert dollar amounts into YNAB-style milliunits when building display rows.
- Mark these rows with `source: apple_wallet` and `cleared: pending`.

The budget math should become:

```text
spent = included YNAB outflows + unreconciled provisional outflows
assigned = FLEXIBLE_BUDGET
```

## Reconciliation

When YNAB imports the same charge later, stop counting the provisional row so
the display does not double-count.

Initial match rule:

```text
same amount
same or nearby date
similar normalized merchant/payee text
same card/source when available
```

If a YNAB row matches a provisional row, the snapshot keeps the provisional row
visible in the dashboard but marks it excluded with reason `matched ynab`. It
does not count toward the progress bar.

The first run after adding this feature should establish a baseline and should
not trigger smart plug behavior for old transactions.

## Apple Card Shortcut Test

In Shortcuts:

1. Create a personal automation using the Wallet/Transaction trigger.
2. Select Apple Card.
3. Set it to run immediately.
4. Build a Dictionary with source, merchant, amount, card, and occurred_at.
5. Add Get Contents of URL after the Dictionary.
6. Use a webhook.site URL while testing.
7. Set Method to POST and Request Body to JSON.
8. Confirm webhook.site receives the JSON after a real Apple Pay transaction.

Once this works, replace the webhook.site URL with the hosted app endpoint:

```text
https://budgetthingy.vercel.app/api/provisional-transaction?key=<DASHBOARD_KEY>
```

Known limitation: this is expected to catch Wallet/Apple Pay transactions. It
may not catch physical card purchases, subscriptions, or manually entered card
number purchases.

## Citi And Other Cards

For Citi, the likely real-time-ish path is transaction alerts, not a consumer
pending transaction API.

Possible feeds:

- Citi email alert for purchases above the lowest allowed threshold.
- Citi SMS alert parsed by an iPhone Shortcut.
- Apple Wallet transaction automation for Citi card Apple Pay purchases.

These should feed the same `/api/provisional-transaction` endpoint with
`source: citi_alert` or `source: apple_wallet`.

## Future Polling And Smart Plug

Future desired schedule:

```text
9:00 AM                       1 request
12:00 PM through 9:30 PM      20 requests, every 30 minutes
11:00 PM                      1 request
12:00 AM                      1 request
1:00 AM                       1 request
                               24 total
```

Do not include a 10:00 PM poll if the goal is exactly 24 requests per day.
12:00 PM through 10:00 PM, inclusive, plus 9:00 AM, 11:00 PM, 12:00 AM, and
1:00 AM would be 25 requests.

Smart plug behavior:

```text
new transaction detected
-> turn plug on
-> wait 60 seconds
-> turn plug off
```

Use explicit on/off commands, not toggle. Add a lock or cooldown so overlapping
polls cannot fight each other. A Home Assistant webhook is the preferred trigger
if available; direct smart plug APIs or IFTTT webhooks are backups.

## Open Questions

- What exact JSON does the iPhone Transaction automation send?
- Does Apple Wallet expose merchant and amount in stable fields on this phone?
- Which Citi alert channel is easiest to ingest: email, SMS, or Wallet?
- Should provisional transactions show in the existing dashboard table by
  default, or behind a filter?
- Should the e-paper display update immediately after a provisional transaction,
  or only at the existing board wake schedule?

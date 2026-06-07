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
FLEXIBLE_BUDGET=0
```

By default, the display counts every visible YNAB category group except `Fixed`, `Internal Master Category`, and `Credit Card Payments`. Set `EXCLUDED_GROUP_NAMES` if your fixed-cost group has a different name or you want to exclude more groups.

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

## Local Checks

```bash
python -m pytest -q
python -m py_compile api/index.py api/generate.py api/display.py
```

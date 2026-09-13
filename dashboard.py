import json
import os
import socket
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from budget_pace import build_budget_bin, fetch_budget_snapshot
from transaction_overrides import (
    load_provisional_attempts,
    load_store,
    record_provisional_attempt,
    record_provisional_transaction,
    record_reprint,
    set_budget,
    set_decision,
)


ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = int(os.environ.get("BUDGET_DASHBOARD_PORT", "8765"))
PUBLIC_ASSETS = {
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
    "/ios-icon.png": ("ios-icon.png", "image/png"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
    "/app-preview.png": ("app-preview.png", "image/png"),
    "/screenshot-mobile.png": ("screenshot-mobile.png", "image/png"),
}


def _dashboard_key(parsed) -> str:
    return (parse_qs(parsed.query).get("key") or [""])[0]


def _manifest_payload(key: str = "") -> dict:
    start_url = f"/?key={key}" if key else "/"
    return {
        "name": "Budget Dashboard",
        "short_name": "Budget",
        "description": "Month-to-date budget pace and card spending dashboard.",
        "start_url": start_url,
        "scope": "/",
        "display": "standalone",
        "background_color": "#0b0f14",
        "theme_color": "#0b0f14",
        "icons": [
            {
                "src": "/ios-icon.png",
                "sizes": "1024x1024",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": "/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
        "screenshots": [
            {
                "src": "/screenshot-mobile.png",
                "sizes": "1290x2796",
                "type": "image/png",
                "form_factor": "narrow",
            }
        ],
    }


def _public_asset(path: str) -> tuple[bytes, str] | None:
    asset = PUBLIC_ASSETS.get(path)
    if asset is None:
        return None
    filename, content_type = asset
    with open(os.path.join(ROOT, "public", filename), "rb") as f:
        return f.read(), content_type


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Budget Dashboard</title>
  <meta name="description" content="Month-to-date budget pace and card spending dashboard.">
  <meta name="application-name" content="Budget Dashboard">
  <meta name="theme-color" content="#0b0f14">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="Budget">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta property="og:title" content="Budget Dashboard">
  <meta property="og:description" content="Month-to-date budget pace and card spending dashboard.">
  <meta property="og:image" content="/app-preview.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="icon" type="image/png" sizes="192x192" href="/icon-192.png">
  <link rel="icon" type="image/png" sizes="512x512" href="/icon-512.png">
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b0f14;
      --surface: #121821;
      --control: #17202a;
      --line: #2b3541;
      --row-line: #202936;
      --table-head: #0f151d;
      --excluded-bg: #11171e;
      --text: #e6edf3;
      --muted: #8a96a3;
      --accent: #14b8a6;
      --accent-strong: #2dd4bf;
      --red: #f87171;
      --red-bg: #351919;
      --amber: #eab308;
      --paper: #fbfbf6;
      --black: #050505;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      border-bottom: 1px solid var(--line);
      background: var(--surface);
    }
    .wrap {
      width: min(1380px, calc(100% - 32px));
      margin: 0 auto;
    }
    .topbar {
      min-height: 68px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    h1 {
      margin: 0;
      font-size: 22px;
      line-height: 1.1;
      font-weight: 650;
      letter-spacing: 0;
    }
    .subtle { color: var(--muted); }
    .title-group {
      min-width: 0;
    }
    .actions, .filters, .segmented {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    button, select, input {
      height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--control);
      color: var(--text);
      font: inherit;
    }
    button {
      padding: 0 12px;
      cursor: pointer;
      font-weight: 600;
    }
    button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: #04110f;
    }
    .icon-button {
      width: 36px;
      padding: 0;
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .icon-button .button-label {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    .icon-button svg {
      width: 17px;
      height: 17px;
      stroke: currentColor;
      stroke-width: 2.2;
      fill: none;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    button.primary:hover { background: var(--accent-strong); }
    button:disabled {
      cursor: progress;
      opacity: 0.65;
    }
    select { padding: 0 34px 0 10px; }
    input {
      width: min(360px, 100%);
      padding: 0 10px;
    }
    main {
      padding: 18px 0 28px;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(8, minmax(118px, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .metric {
      min-height: 86px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      padding: 12px;
    }
    .metric .label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
    }
    .metric .value {
      margin-top: 7px;
      font-size: 24px;
      line-height: 1.1;
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .metric .note {
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
    }
    .metric .value.positive { color: var(--accent-strong); }
    .budget-value {
      display: flex;
      align-items: baseline;
      gap: 6px;
    }
    .budget-edit {
      height: auto;
      min-width: 0;
      padding: 2px 6px;
      border: 1px solid var(--line);
      border-radius: 4px;
      background: var(--control);
      color: var(--muted);
      font-size: 11px;
      font-weight: 650;
      cursor: pointer;
    }
    .budget-edit:hover {
      color: var(--text);
      border-color: var(--accent);
    }
    .budget-input {
      width: 100%;
      padding: 0;
      border: none;
      border-bottom: 1px solid var(--accent);
      border-radius: 0;
      background: transparent;
      color: var(--text);
      font-size: 24px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    .budget-input:focus {
      outline: none;
      border-bottom-color: var(--accent-strong);
    }
    .status {
      min-height: 22px;
      color: var(--muted);
      margin: 0 0 12px;
    }
    .status.error { color: var(--red); }
    .pace-panel {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      padding: 13px 14px 12px;
      margin: 0 0 12px;
    }
    .pace-head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    .pace-note {
      color: var(--muted);
      font-size: 12px;
      text-align: right;
    }
    .pace-bar {
      position: relative;
      height: 34px;
      border: 2px solid var(--paper);
      background: var(--black);
      margin: 18px 4px 10px;
    }
    .pace-fill,
    .pace-overage {
      position: absolute;
      top: 0;
      bottom: 0;
      left: 0;
      width: 0;
      transition: width 140ms ease, left 140ms ease;
    }
    .pace-fill { background: var(--paper); }
    .pace-overage { background: var(--red); }
    .pace-tick {
      position: absolute;
      top: -18px;
      bottom: -18px;
      left: 0;
      width: 4px;
      background: var(--amber);
      transform: translateX(-2px);
      transition: left 140ms ease;
    }
    .pace-scale {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
      font-variant-numeric: tabular-nums;
    }
    .pace-scale span:nth-child(2) { text-align: center; }
    .pace-scale span:last-child { text-align: right; }
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 330px;
      gap: 14px;
      align-items: start;
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
    }
    .panel-head {
      min-height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
    }
    h2 {
      margin: 0;
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0;
    }
    .table-wrap {
      overflow-x: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 920px;
    }
    th, td {
      padding: 9px 10px;
      border-bottom: 1px solid var(--row-line);
      text-align: left;
      vertical-align: middle;
      white-space: nowrap;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      background: var(--table-head);
    }
    td.amount, th.amount {
      text-align: right;
      font-variant-numeric: tabular-nums;
    }
    tr.excluded td {
      color: #7f8a96;
      background: var(--excluded-bg);
    }
    .payee {
      max-width: 260px;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .memo {
      max-width: 180px;
      color: var(--muted);
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 2px 8px;
      border-radius: 999px;
      background: #073f3a;
      color: #7ddbd2;
      font-size: 12px;
      font-weight: 700;
    }
    .pill.out {
      background: var(--red-bg);
      color: var(--red);
    }
    .status-stack {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .clearance {
      color: var(--muted);
      font-size: 12px;
      text-transform: capitalize;
    }
    .segmented {
      gap: 0;
      flex-wrap: nowrap;
    }
    .segmented button {
      width: 58px;
      height: 30px;
      padding: 0;
      border-radius: 0;
      border-right-width: 0;
      font-size: 12px;
    }
    .segmented button:first-child { border-radius: 6px 0 0 6px; }
    .segmented button:last-child {
      border-radius: 0 6px 6px 0;
      border-right-width: 1px;
    }
    .segmented button.active {
      background: var(--text);
      border-color: var(--text);
      color: var(--bg);
    }
    .decision-control {
      display: inline-flex;
      align-items: center;
    }
    .decision-select {
      display: none;
      width: 86px;
      height: 30px;
      padding: 0 26px 0 9px;
      font-size: 12px;
      font-weight: 700;
    }
    .side-list {
      padding: 8px 12px 12px;
    }
    .account-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      padding: 9px 0;
      border-bottom: 1px solid var(--row-line);
    }
    .account-row:last-child { border-bottom: 0; }
    .account-name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-weight: 650;
    }
    .account-count {
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .account-amount {
      font-variant-numeric: tabular-nums;
      font-weight: 700;
    }
    @media (max-width: 980px) {
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .layout { grid-template-columns: 1fr; }
      .topbar { padding: 12px 0; }
      .pace-head { align-items: flex-start; flex-direction: column; }
      .pace-note { text-align: left; }
      input { width: 100%; }
    }
    @media (max-width: 720px) {
      .wrap { width: min(100% - 20px, 1380px); }
      main { padding: 10px 0 18px; }
      .topbar {
        min-height: 54px;
        gap: 8px;
      }
      h1 { font-size: 19px; }
      .title-group .subtle { font-size: 12px; }
      .actions {
        flex-wrap: nowrap;
        gap: 6px;
      }
      button {
        height: 32px;
        padding: 0 10px;
        font-size: 13px;
      }
      .icon-button {
        width: 32px;
        padding: 0;
      }
      .metrics {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 6px;
        margin-bottom: 10px;
      }
      .metric {
        min-height: 64px;
        padding: 8px;
      }
      .metric .label {
        font-size: 10px;
        line-height: 1.1;
      }
      .metric .value {
        margin-top: 5px;
        font-size: 18px;
      }
      .budget-input { font-size: 18px; }
      .metric .note {
        margin-top: 2px;
        font-size: 11px;
        line-height: 1.2;
      }
      .pace-panel {
        padding: 10px;
        margin-bottom: 10px;
      }
      .pace-head {
        gap: 4px;
        margin-bottom: 8px;
      }
      .pace-bar {
        height: 26px;
        margin: 14px 3px 8px;
      }
      .pace-tick {
        top: -14px;
        bottom: -14px;
      }
      .panel-head {
        align-items: stretch;
        flex-direction: column;
        min-height: 0;
        padding: 8px;
        gap: 8px;
      }
      .filters {
        align-items: stretch;
        width: 100%;
        gap: 6px;
      }
      .filters input,
      .filters select {
        width: 100%;
        height: 32px;
        font-size: 13px;
      }
      .table-wrap { overflow: visible; }
      table {
        min-width: 0;
        border-collapse: separate;
      }
      table,
      tbody,
      tr,
      td {
        display: block;
      }
      thead { display: none; }
      tbody {
        display: grid;
        gap: 6px;
        padding: 6px;
      }
      tr {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 4px 8px;
        border: 1px solid var(--line);
        border-radius: 6px;
        background: var(--surface);
        padding: 8px;
      }
      tr.excluded { background: var(--excluded-bg); }
      td {
        min-width: 0;
        padding: 0;
        border-bottom: 0;
        white-space: normal;
      }
      tr.excluded td {
        color: inherit;
        background: transparent;
      }
      td::before {
        content: attr(data-label);
        display: block;
        margin-bottom: 1px;
        color: var(--muted);
        font-size: 10px;
        line-height: 1;
        font-weight: 700;
        text-transform: uppercase;
      }
      td[data-label="Date"] {
        grid-column: 1;
        grid-row: 1;
        color: var(--muted);
        font-size: 12px;
      }
      td[data-label="Amount"] {
        grid-column: 2;
        grid-row: 1;
        align-self: start;
        font-size: 15px;
        font-weight: 700;
        text-align: right;
      }
      td[data-label="Payee"] {
        grid-column: 1 / -1;
        grid-row: 2;
        font-size: 15px;
        line-height: 1.25;
        font-weight: 700;
      }
      td[data-label="Account"] {
        grid-column: 1;
        grid-row: 3;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.2;
      }
      td[data-label="Memo"] {
        grid-column: 1 / -1;
        grid-row: 4;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.25;
      }
      td[data-label="Status"] {
        display: none;
      }
      td[data-label="Decision"] {
        grid-column: 2;
        grid-row: 3;
        justify-self: end;
      }
      td[data-label="Date"]::before,
      td[data-label="Amount"]::before,
      td[data-label="Payee"]::before,
      td[data-label="Account"]::before,
      td[data-label="Memo"]::before,
      td[data-label="Status"]::before,
      td[data-label="Decision"]::before {
        display: none;
      }
      .payee,
      .memo {
        max-width: none;
        overflow: visible;
        text-overflow: clip;
      }
      .status-stack {
        flex-wrap: wrap;
        justify-content: flex-end;
      }
      .pill {
        min-height: 20px;
        padding: 1px 7px;
        font-size: 11px;
      }
      .clearance { font-size: 11px; }
      td.empty { display: none; }
      .decision-control .segmented {
        display: none;
      }
      .decision-select {
        display: block;
        width: 82px;
        height: 28px;
        padding: 0 24px 0 8px;
      }
      .segmented button {
        flex: 1;
        min-width: 0;
        height: 28px;
      }
      .side-list { padding: 5px 8px 8px; }
      .account-row { padding: 7px 0; }
      .pace-scale {
        grid-template-columns: 1fr;
        gap: 2px;
        font-size: 11px;
      }
      .pace-scale span,
      .pace-scale span:nth-child(2),
      .pace-scale span:last-child {
        text-align: left;
      }
    }
  </style>
</head>
<body>
  <header>
    <div class="wrap topbar">
      <div class="title-group">
        <h1>Budget Dashboard</h1>
        <div class="subtle" id="monthLabel">Loading</div>
      </div>
      <div class="actions">
        <button class="icon-button" id="refreshButton" aria-label="Refresh" title="Refresh">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M21 12a9 9 0 0 1-15.1 6.6"></path>
            <path d="M3 12A9 9 0 0 1 18.1 5.4"></path>
            <path d="M21 5v5h-5"></path>
            <path d="M3 19v-5h5"></path>
          </svg>
          <span class="button-label">Refresh</span>
        </button>
        <button class="primary" id="reprintButton">Reprint Now</button>
      </div>
    </div>
  </header>
  <main class="wrap">
    <section class="metrics" aria-label="Budget summary">
      <div class="metric"><div class="label">State</div><div class="value" id="stateValue">-</div><div class="note" id="paceNote">-</div></div>
      <div class="metric"><div class="label">Spent</div><div class="value" id="spentValue">-</div><div class="note" id="countNote">-</div></div>
      <div class="metric"><div class="label">Expected</div><div class="value" id="expectedValue">-</div><div class="note" id="dayNote">-</div></div>
      <div class="metric">
        <div class="label">Assigned</div>
        <div class="value budget-value">
          <span id="assignedValue">-</span>
          <button type="button" class="budget-edit" id="budgetEditButton" aria-label="Edit monthly budget" title="Edit monthly budget">Edit</button>
          <input type="number" class="budget-input" id="budgetInput" min="0" step="10" inputmode="decimal" aria-label="Monthly budget" hidden>
        </div>
        <div class="note" id="budgetNote">Monthly budget</div>
      </div>
      <div class="metric"><div class="label">Remaining</div><div class="value" id="remainingValue">-</div><div class="note">Month total</div></div>
      <div class="metric"><div class="label">Saved Last Month</div><div class="value" id="savedLastMonthValue">-</div><div class="note" id="savedLastMonthNote">-</div></div>
      <div class="metric"><div class="label">Projected Savings</div><div class="value" id="projectedSavingsValue">-</div><div class="note" id="projectedSavingsNote">-</div></div>
      <div class="metric"><div class="label">Overrides</div><div class="value" id="overrideValue">-</div><div class="note" id="reprintNote">No reprint yet</div></div>
    </section>
    <section class="pace-panel" aria-label="Budget progress">
      <div class="pace-head">
        <h2>Progress</h2>
        <div class="pace-note" id="clearanceNote">-</div>
      </div>
      <div class="pace-bar">
        <div class="pace-fill" id="progressFill"></div>
        <div class="pace-overage" id="progressOverage"></div>
        <div class="pace-tick" id="progressTick"></div>
      </div>
      <div class="pace-scale">
        <span id="progressSpentLabel">-</span>
        <span id="progressExpectedLabel">-</span>
        <span id="progressAssignedLabel">-</span>
      </div>
    </section>
    <p class="status" id="statusLine"></p>
    <section class="layout">
      <div class="panel">
        <div class="panel-head">
          <h2>Purchases</h2>
          <div class="filters">
            <input id="searchInput" type="search" placeholder="Search payee, memo, account">
            <select id="filterSelect" aria-label="Filter purchases">
              <option value="all">All</option>
              <option value="included">Included</option>
              <option value="excluded">Excluded</option>
              <option value="uncleared">Pending/Uncleared</option>
              <option value="overridden">Manual</option>
            </select>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Account</th>
                <th>Payee</th>
                <th>Memo</th>
                <th>Status</th>
                <th class="amount">Amount</th>
                <th>Decision</th>
              </tr>
            </thead>
            <tbody id="transactionBody"></tbody>
          </table>
        </div>
      </div>
      <aside class="panel">
        <div class="panel-head">
          <h2>Accounts</h2>
        </div>
        <div class="side-list" id="accountList"></div>
      </aside>
    </section>
  </main>
  <script>
    let dashboard = null;
    const query = new URLSearchParams(window.location.search);
    const queryKey = query.get("key");
    if (queryKey) localStorage.setItem("budgetDashboardKey", queryKey);
    const dashboardKey = queryKey || localStorage.getItem("budgetDashboardKey") || "";
    const manifestLink = document.createElement("link");
    manifestLink.rel = "manifest";
    manifestLink.href = dashboardKey ? `/manifest.webmanifest?key=${encodeURIComponent(dashboardKey)}` : "/manifest.webmanifest";
    document.head.append(manifestLink);
    const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
    const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

    const els = {
      monthLabel: document.getElementById("monthLabel"),
      stateValue: document.getElementById("stateValue"),
      paceNote: document.getElementById("paceNote"),
      spentValue: document.getElementById("spentValue"),
      countNote: document.getElementById("countNote"),
      expectedValue: document.getElementById("expectedValue"),
      dayNote: document.getElementById("dayNote"),
      assignedValue: document.getElementById("assignedValue"),
      budgetEditButton: document.getElementById("budgetEditButton"),
      budgetInput: document.getElementById("budgetInput"),
      budgetNote: document.getElementById("budgetNote"),
      remainingValue: document.getElementById("remainingValue"),
      savedLastMonthValue: document.getElementById("savedLastMonthValue"),
      savedLastMonthNote: document.getElementById("savedLastMonthNote"),
      projectedSavingsValue: document.getElementById("projectedSavingsValue"),
      projectedSavingsNote: document.getElementById("projectedSavingsNote"),
      overrideValue: document.getElementById("overrideValue"),
      reprintNote: document.getElementById("reprintNote"),
      clearanceNote: document.getElementById("clearanceNote"),
      progressFill: document.getElementById("progressFill"),
      progressOverage: document.getElementById("progressOverage"),
      progressTick: document.getElementById("progressTick"),
      progressSpentLabel: document.getElementById("progressSpentLabel"),
      progressExpectedLabel: document.getElementById("progressExpectedLabel"),
      progressAssignedLabel: document.getElementById("progressAssignedLabel"),
      statusLine: document.getElementById("statusLine"),
      transactionBody: document.getElementById("transactionBody"),
      accountList: document.getElementById("accountList"),
      searchInput: document.getElementById("searchInput"),
      filterSelect: document.getElementById("filterSelect"),
      refreshButton: document.getElementById("refreshButton"),
      reprintButton: document.getElementById("reprintButton")
    };

    function setStatus(message, isError = false) {
      els.statusLine.textContent = message || "";
      els.statusLine.classList.toggle("error", isError);
    }

    function includesSearch(row, query) {
      if (!query) return true;
      const haystack = [row.date, row.account, row.payee, row.memo, row.reason, row.cleared, row.source].join(" ").toLowerCase();
      return haystack.includes(query);
    }

    function shortDate(value) {
      const parts = String(value || "").split("-");
      if (parts.length !== 3) return value || "";
      const month = Number(parts[1]);
      const day = Number(parts[2]);
      if (!month || !day) return value || "";
      return `${month}/${day}`;
    }

    function pct(value) {
      const safe = Math.max(0, Math.min(Number(value) || 0, 1));
      return `${(safe * 100).toFixed(2)}%`;
    }

    function clearanceText() {
      const clearance = dashboard.counts.clearance || {};
      const total = clearance.total || {};
      const included = clearance.included || {};
      const includedUncleared = included.uncleared || 0;
      const totalUncleared = total.uncleared || 0;
      const includedPending = included.pending || 0;
      const totalPending = total.pending || 0;
      return `${includedPending} pending and ${includedUncleared} uncleared included, ${totalPending} pending and ${totalUncleared} uncleared total`;
    }

    function visibleRows() {
      if (!dashboard) return [];
      const query = els.searchInput.value.trim().toLowerCase();
      const filter = els.filterSelect.value;
      return dashboard.transactions.filter((row) => {
        if (!includesSearch(row, query)) return false;
        if (filter === "included") return row.included;
        if (filter === "excluded") return !row.included;
        if (filter === "uncleared") return row.cleared === "uncleared" || row.cleared === "pending";
        if (filter === "overridden") return row.decision !== "auto";
        return true;
      });
    }

    function decisionButton(row, value, label) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.className = row.decision === value ? "active" : "";
      button.addEventListener("click", () => setDecision(row.line_id, value));
      return button;
    }

    function decisionSelect(row) {
      const select = document.createElement("select");
      select.className = "decision-select";
      select.setAttribute("aria-label", `Decision for ${row.payee}`);
      for (const [value, label] of [["auto", "Auto"], ["include", "In"], ["exclude", "Out"]]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        select.append(option);
      }
      select.value = row.decision || "auto";
      select.addEventListener("change", () => setDecision(row.line_id, select.value));
      return select;
    }

    function decisionControl(row) {
      const control = document.createElement("div");
      control.className = "decision-control";
      const segmented = document.createElement("div");
      segmented.className = "segmented";
      segmented.append(
        decisionButton(row, "auto", "Auto"),
        decisionButton(row, "include", "In"),
        decisionButton(row, "exclude", "Out")
      );
      control.append(segmented, decisionSelect(row));
      return control;
    }

    function renderTransactions() {
      els.transactionBody.replaceChildren();
      const labels = ["Date", "Account", "Payee", "Memo", "Status", "Amount", "Decision"];
      for (const row of visibleRows()) {
        const tr = document.createElement("tr");
        tr.className = row.included ? "" : "excluded";

        const status = document.createElement("span");
        status.className = row.included ? "pill" : "pill out";
        status.textContent = row.included ? "Included" : "Excluded";
        status.title = `${row.reason}${row.cleared ? `, ${row.cleared}` : ""}`;

        const statusStack = document.createElement("div");
        statusStack.className = "status-stack";
        statusStack.append(status);
        if (row.cleared) {
          const clearance = document.createElement("span");
          clearance.className = "clearance";
          clearance.textContent = row.cleared;
          statusStack.append(clearance);
        }

        const cells = [
          shortDate(row.date),
          row.account,
          row.payee,
          row.memo || "",
          statusStack,
          money.format(row.amount),
          decisionControl(row)
        ];

        cells.forEach((value, index) => {
          const td = document.createElement("td");
          td.dataset.label = labels[index];
          if (index === 2) td.className = "payee";
          if (index === 3) td.className = "memo";
          if (index === 5) td.className = "amount";
          if (index === 3 && !value) td.classList.add("empty");
          if (typeof value === "string") td.textContent = value;
          else td.append(value);
          tr.append(td);
        });
        els.transactionBody.append(tr);
      }
    }

    function renderAccounts() {
      els.accountList.replaceChildren();
      if (!dashboard.account_totals.length) {
        const empty = document.createElement("div");
        empty.className = "subtle";
        empty.textContent = "No included spending yet.";
        els.accountList.append(empty);
        return;
      }
      for (const item of dashboard.account_totals) {
        const row = document.createElement("div");
        row.className = "account-row";
        const left = document.createElement("div");
        const name = document.createElement("div");
        name.className = "account-name";
        name.textContent = item.account;
        const count = document.createElement("div");
        count.className = "account-count";
        count.textContent = `${item.count} included purchases`;
        left.append(name, count);
        const amount = document.createElement("div");
        amount.className = "account-amount";
        amount.textContent = money.format(item.spent);
        row.append(left, amount);
        els.accountList.append(row);
      }
    }

    function renderSummary() {
      els.monthLabel.textContent = dashboard.month;
      els.stateValue.textContent = dashboard.state;
      els.paceNote.textContent = `${number.format(dashboard.pace)}x expected pace`;
      els.spentValue.textContent = money.format(dashboard.spent);
      els.countNote.textContent = `${dashboard.counts.included} included of ${dashboard.counts.total}`;
      els.expectedValue.textContent = money.format(dashboard.expected);
      els.dayNote.textContent = `Day ${dashboard.day} of ${dashboard.days_in_month}`;
      els.assignedValue.textContent = money.format(dashboard.assigned);
      els.budgetNote.textContent = budgetNoteText();
      els.remainingValue.textContent = money.format(dashboard.remaining);
      els.overrideValue.textContent = dashboard.counts.overridden;
      renderSavings();
      if (dashboard.reprint && dashboard.reprint.requested_at) {
        els.reprintNote.textContent = dashboard.reprint.requested_at.replace("T", " ").slice(0, 19);
      } else {
        els.reprintNote.textContent = "No reprint yet";
      }

      const progress = dashboard.progress || {};
      els.progressFill.style.width = pct(progress.on_pace_fill);
      els.progressOverage.style.left = pct(progress.tick);
      els.progressOverage.style.width = pct(progress.overage);
      els.progressTick.style.left = pct(progress.tick);
      els.progressTick.style.opacity = dashboard.assigned > 0 ? "1" : "0";
      els.progressSpentLabel.textContent = `${money.format(dashboard.spent)} spent`;
      els.progressExpectedLabel.textContent = `${money.format(dashboard.expected)} expected`;
      els.progressAssignedLabel.textContent = `${money.format(dashboard.assigned)} assigned`;
      els.clearanceNote.textContent = clearanceText();
    }

    const monthName = new Intl.DateTimeFormat("en-US", { month: "long", timeZone: "UTC" });

    function monthLabel(value) {
      const parts = String(value || "").split("-");
      if (parts.length < 2) return "Last month";
      const parsed = new Date(Date.UTC(Number(parts[0]), Number(parts[1]) - 1, 1));
      return Number.isNaN(parsed.getTime()) ? "Last month" : monthName.format(parsed);
    }

    function budgetNoteText() {
      if (dashboard.budget_source === "env") return "From FLEXIBLE_BUDGET";
      if (dashboard.budget_source === "ynab") return "YNAB assigned total";
      return "Monthly budget";
    }

    function renderSavings() {
      const savings = dashboard.savings || {};
      const lastMonth = savings.last_month || {};
      const thisMonth = savings.this_month || {};

      const saved = dashboard.saved_last_month || 0;
      els.savedLastMonthValue.textContent = money.format(saved);
      els.savedLastMonthValue.classList.toggle("positive", saved > 0);
      els.savedLastMonthNote.textContent = lastMonth.income === undefined
        ? "-"
        : `${monthLabel(lastMonth.month)}: ${money.format(lastMonth.income)} in \u2212 ${money.format(lastMonth.spending)} out`;

      const projected = dashboard.projected_savings || 0;
      els.projectedSavingsValue.textContent = money.format(projected);
      els.projectedSavingsValue.classList.toggle("positive", projected > 0);
      els.projectedSavingsNote.textContent = thisMonth.projected_spending === undefined
        ? "-"
        : `${money.format(thisMonth.projected_income)} in \u2212 ${money.format(thisMonth.projected_spending)} projected out`;
    }

    function startBudgetEdit() {
      if (!dashboard) return;
      els.budgetInput.value = String(Math.round((dashboard.assigned || 0) * 100) / 100);
      els.budgetInput.hidden = false;
      els.assignedValue.hidden = true;
      els.budgetEditButton.hidden = true;
      els.budgetInput.focus();
      els.budgetInput.select();
    }

    function stopBudgetEdit() {
      els.budgetInput.hidden = true;
      els.assignedValue.hidden = false;
      els.budgetEditButton.hidden = false;
    }

    async function saveBudget() {
      const raw = els.budgetInput.value.trim();
      stopBudgetEdit();
      if (raw === "") return;

      const amount = Number(raw);
      if (!Number.isFinite(amount) || amount < 0) {
        setStatus("Budget must be a number of zero or more.", true);
        return;
      }
      if (amount === dashboard.assigned) return;

      setStatus("Saving budget...");
      try {
        dashboard = await fetchJson("/api/budget", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ monthly: amount })
        });
        render();
        setStatus(`Budget set to ${money.format(dashboard.assigned)} per month.`);
      } catch (error) {
        setStatus(error.message, true);
      }
    }

    function render() {
      renderSummary();
      renderTransactions();
      renderAccounts();
    }

    function apiUrl(url) {
      if (!dashboardKey) return url;
      const separator = url.includes("?") ? "&" : "?";
      return `${url}${separator}key=${encodeURIComponent(dashboardKey)}`;
    }

    async function fetchJson(url, options = {}) {
      const response = await fetch(apiUrl(url), options);
      const payload = await response.json();
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || `Request failed: ${response.status}`);
      }
      return payload;
    }

    async function loadDashboard() {
      els.refreshButton.disabled = true;
      setStatus("Refreshing budget data...");
      try {
        dashboard = await fetchJson("/api/dashboard");
        render();
        setStatus(`Loaded ${dashboard.counts.total} current-month purchases.`);
      } catch (error) {
        setStatus(error.message, true);
      } finally {
        els.refreshButton.disabled = false;
      }
    }

    async function setDecision(lineId, decision) {
      setStatus("Saving decision...");
      try {
        dashboard = await fetchJson("/api/overrides", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ line_id: lineId, decision })
        });
        render();
        setStatus("Decision saved.");
      } catch (error) {
        setStatus(error.message, true);
      }
    }

    async function reprintNow() {
      els.reprintButton.disabled = true;
      setStatus("Building e-paper frame...");
      try {
        const payload = await fetchJson("/api/reprint", { method: "POST" });
        dashboard = payload.dashboard;
        render();
        setStatus(`Frame regenerated for next board wake: ${payload.metadata.bytes} bytes.`);
      } catch (error) {
        setStatus(error.message, true);
      } finally {
        els.reprintButton.disabled = false;
      }
    }

    els.refreshButton.addEventListener("click", loadDashboard);
    els.reprintButton.addEventListener("click", reprintNow);
    els.budgetEditButton.addEventListener("click", startBudgetEdit);
    els.budgetInput.addEventListener("blur", saveBudget);
    els.budgetInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        els.budgetInput.blur();
      } else if (event.key === "Escape") {
        event.preventDefault();
        els.budgetInput.value = "";
        stopBudgetEdit();
      }
    });
    els.searchInput.addEventListener("input", renderTransactions);
    els.filterSelect.addEventListener("change", renderTransactions);
    loadDashboard();
  </script>
</body>
</html>
"""


def _dashboard_payload() -> dict:
    store = load_store()
    payload = fetch_budget_snapshot(store)
    payload["reprint"] = store.get("reprint", {})
    return payload


def _reprint_token() -> str:
    reprint = load_store().get("reprint", {})
    return str(int(reprint.get("count", 0)))


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            if path in {"/", "/index.html"}:
                self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/manifest.webmanifest":
                self._send_manifest(_dashboard_key(parsed))
            elif asset := _public_asset(path):
                body, content_type = asset
                self._send(body=body, status=200, content_type=content_type, headers={"Cache-Control": "public, max-age=86400"})
            elif path == "/api/dashboard":
                self._send_json(200, _dashboard_payload())
            elif path == "/api/provisional-attempts":
                self._send_json(200, {"ok": True, "attempts": load_provisional_attempts()})
            elif path == "/api/display":
                body, _ = build_budget_bin(load_store())
                self._send(
                    200,
                    body,
                    "application/octet-stream",
                    {"Cache-Control": "no-store"},
                )
            elif path == "/api/reprint-token":
                self._send(
                    200,
                    _reprint_token().encode("utf-8"),
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
            elif path == "/api/preview.png":
                self._preview_png()
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        payload = {}
        try:
            if path == "/api/overrides":
                payload = self._read_json()
                set_decision(str(payload.get("line_id", "")), str(payload.get("decision", "auto")))
                self._send_json(200, _dashboard_payload())
            elif path == "/api/budget":
                payload = self._read_json()
                set_budget(payload.get("monthly"))
                self._send_json(200, _dashboard_payload())
            elif path == "/api/provisional-transaction":
                payload = self._read_json()
                transaction = record_provisional_transaction(payload)
                self._record_provisional_attempt(payload, "accepted", transaction_id=transaction["id"])
                self._send_json(200, {"ok": True, "transaction": transaction})
            elif path == "/api/reprint":
                _, metadata = build_budget_bin(load_store(), output_dir=ROOT)
                reprint = record_reprint(metadata)
                dashboard = _dashboard_payload()
                dashboard["reprint"] = reprint
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "metadata": metadata,
                        "reprint": reprint,
                        "dashboard": dashboard,
                    },
                )
            else:
                self._send_json(404, {"ok": False, "error": "not found"})
        except ValueError as exc:
            if path == "/api/provisional-transaction":
                self._record_provisional_attempt(payload, "rejected", error=str(exc))
            self._send_json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})

    def _record_provisional_attempt(
        self,
        payload: dict,
        status: str,
        error: str = "",
        transaction_id: str = "",
    ) -> None:
        try:
            record_provisional_attempt(payload, status, error=error, transaction_id=transaction_id)
        except Exception:
            pass

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)

    def _preview_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, metadata = build_budget_bin(load_store(), output_dir=tmp)
            with open(metadata["preview_path"], "rb") as f:
                body = f.read()
        self._send(200, body, "image/png", {"Cache-Control": "no-store"})

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send(status, body, "application/json")

    def _send_manifest(self, key: str = "") -> None:
        body = json.dumps(_manifest_payload(key), separators=(",", ":")).encode("utf-8")
        self._send(
            200,
            body,
            "application/manifest+json",
            {"Cache-Control": "no-store"},
        )

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def _local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main() -> None:
    port = DEFAULT_PORT
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"Dashboard: http://127.0.0.1:{port}", flush=True)
    print(f"Network:   http://{_local_ip()}:{port}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

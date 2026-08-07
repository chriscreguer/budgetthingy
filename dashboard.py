import json
import os
import socket
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from budget_pace import build_budget_bin, fetch_budget_snapshot
from transaction_overrides import load_overrides, load_store, record_reprint, set_decision


ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = int(os.environ.get("BUDGET_DASHBOARD_PORT", "8765"))


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Budget Dashboard</title>
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
      grid-template-columns: repeat(6, minmax(130px, 1fr));
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
      border: 2px solid var(--black);
      background: var(--paper);
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
    .pace-fill { background: var(--black); }
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
      .topbar { align-items: flex-start; flex-direction: column; padding: 14px 0; }
      .pace-head { align-items: flex-start; flex-direction: column; }
      .pace-note { text-align: left; }
      input { width: 100%; }
    }
  </style>
</head>
<body>
  <header>
    <div class="wrap topbar">
      <div>
        <h1>Budget Dashboard</h1>
        <div class="subtle" id="monthLabel">Loading</div>
      </div>
      <div class="actions">
        <button id="refreshButton">Refresh</button>
        <button class="primary" id="reprintButton">Reprint Now</button>
      </div>
    </div>
  </header>
  <main class="wrap">
    <section class="metrics" aria-label="Budget summary">
      <div class="metric"><div class="label">State</div><div class="value" id="stateValue">-</div><div class="note" id="paceNote">-</div></div>
      <div class="metric"><div class="label">Spent</div><div class="value" id="spentValue">-</div><div class="note" id="countNote">-</div></div>
      <div class="metric"><div class="label">Expected</div><div class="value" id="expectedValue">-</div><div class="note" id="dayNote">-</div></div>
      <div class="metric"><div class="label">Assigned</div><div class="value" id="assignedValue">-</div><div class="note">Flexible budget</div></div>
      <div class="metric"><div class="label">Remaining</div><div class="value" id="remainingValue">-</div><div class="note">Month total</div></div>
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
              <option value="uncleared">Uncleared</option>
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
      remainingValue: document.getElementById("remainingValue"),
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
      const haystack = [row.account, row.payee, row.memo, row.reason, row.cleared].join(" ").toLowerCase();
      return haystack.includes(query);
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
      return `${includedUncleared} uncleared included, ${totalUncleared} uncleared total`;
    }

    function visibleRows() {
      if (!dashboard) return [];
      const query = els.searchInput.value.trim().toLowerCase();
      const filter = els.filterSelect.value;
      return dashboard.transactions.filter((row) => {
        if (!includesSearch(row, query)) return false;
        if (filter === "included") return row.included;
        if (filter === "excluded") return !row.included;
        if (filter === "uncleared") return row.cleared === "uncleared";
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

    function renderTransactions() {
      els.transactionBody.replaceChildren();
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

        const segmented = document.createElement("div");
        segmented.className = "segmented";
        segmented.append(
          decisionButton(row, "auto", "Auto"),
          decisionButton(row, "include", "In"),
          decisionButton(row, "exclude", "Out")
        );

        const cells = [
          row.date,
          row.account,
          row.payee,
          row.memo || "",
          statusStack,
          money.format(row.amount),
          segmented
        ];

        cells.forEach((value, index) => {
          const td = document.createElement("td");
          if (index === 2) td.className = "payee";
          if (index === 3) td.className = "memo";
          if (index === 5) td.className = "amount";
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
      els.remainingValue.textContent = money.format(dashboard.remaining);
      els.overrideValue.textContent = dashboard.counts.overridden;
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
    els.searchInput.addEventListener("input", renderTransactions);
    els.filterSelect.addEventListener("change", renderTransactions);
    loadDashboard();
  </script>
</body>
</html>
"""


def _dashboard_payload() -> dict:
    overrides = {"transactions": load_overrides()}
    payload = fetch_budget_snapshot(overrides)
    payload["reprint"] = load_store().get("reprint", {})
    return payload


def _reprint_token() -> str:
    reprint = load_store().get("reprint", {})
    return str(int(reprint.get("count", 0)))


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            if path in {"/", "/index.html"}:
                self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/dashboard":
                self._send_json(200, _dashboard_payload())
            elif path == "/api/display":
                body, _ = build_budget_bin({"transactions": load_overrides()})
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
        try:
            if path == "/api/overrides":
                payload = self._read_json()
                set_decision(str(payload.get("line_id", "")), str(payload.get("decision", "auto")))
                self._send_json(200, _dashboard_payload())
            elif path == "/api/reprint":
                _, metadata = build_budget_bin({"transactions": load_overrides()}, output_dir=ROOT)
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
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)

    def _preview_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, metadata = build_budget_bin({"transactions": load_overrides()}, output_dir=tmp)
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

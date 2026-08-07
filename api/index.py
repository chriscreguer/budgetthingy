import json
import os
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api.display import _load_budget_bin
from api.generate import _generate_summary
from budget_pace import build_budget_bin
from dashboard import HTML, _dashboard_payload, _reprint_token
from transaction_overrides import load_overrides, record_reprint, set_decision


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path in {"/", "/dashboard", "/api/index"}:
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/dashboard":
            if not self._authorized(parsed):
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            self._dashboard()
        elif path == "/api/reprint-token":
            self._send(
                200,
                _reprint_token().encode("utf-8"),
                "text/plain; charset=utf-8",
                {"Cache-Control": "no-store"},
            )
        elif path == "/api/generate":
            self._generate()
        elif path == "/api/display":
            self._display()
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path in {"/api/overrides", "/api/reprint"} and not self._authorized(parsed):
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return

        if path == "/api/overrides":
            self._overrides()
        elif path == "/api/reprint":
            self._reprint()
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def _authorized(self, parsed) -> bool:
        required = os.environ.get("DASHBOARD_KEY", "")
        if not required:
            return True

        query = parse_qs(parsed.query)
        supplied = (query.get("key") or [""])[0] or self.headers.get("X-Dashboard-Key", "")
        return supplied == required

    def _dashboard(self) -> None:
        try:
            self._send_json(200, _dashboard_payload())
        except Exception as exc:
            self._error(exc)

    def _overrides(self) -> None:
        try:
            payload = self._read_json()
            set_decision(str(payload.get("line_id", "")), str(payload.get("decision", "auto")))
            self._send_json(200, _dashboard_payload())
        except Exception as exc:
            self._error(exc)

    def _reprint(self) -> None:
        try:
            _, metadata = build_budget_bin({"transactions": load_overrides()})
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
        except Exception as exc:
            self._error(exc)

    def _generate(self) -> None:
        try:
            payload = _generate_summary()
            self._send_json(200, payload)
        except Exception as exc:
            self._error(exc)

    def _display(self) -> None:
        try:
            body = _load_budget_bin()
            self._send(
                200,
                body,
                "application/octet-stream",
                {"Cache-Control": "no-store"},
            )
        except Exception as exc:
            self._send(500, f"ERROR: {exc}".encode("utf-8"), "text/plain")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send(status, body, "application/json")

    def _error(self, exc: Exception) -> None:
        self._send_json(
            500,
            {
                "ok": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
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

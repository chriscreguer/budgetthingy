import asyncio
import json
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from api.display import _load_budget_bin
from api.generate import _generate_and_upload


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        if path == "/api/generate":
            self._generate(self.headers.get("x-vercel-oidc-token"))
        elif path == "/api/display":
            self._display(self.headers.get("x-vercel-oidc-token"))
        else:
            self._send(404, b"not found", "text/plain")

    def _generate(self, blob_token: str | None) -> None:
        try:
            payload = asyncio.run(_generate_and_upload(blob_token))
            body = json.dumps(payload).encode("utf-8")
            self._send(200, body, "application/json")
        except Exception as exc:
            body = json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            ).encode("utf-8")
            self._send(500, body, "application/json")

    def _display(self, blob_token: str | None) -> None:
        try:
            body = asyncio.run(_load_budget_bin(blob_token))
            if body is None:
                self._send(
                    404,
                    b"budget.bin has not been generated yet",
                    "text/plain",
                )
                return

            self._send(
                200,
                body,
                "application/octet-stream",
                {"Cache-Control": "no-store"},
            )
        except Exception as exc:
            self._send(500, f"ERROR: {exc}".encode("utf-8"), "text/plain")

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

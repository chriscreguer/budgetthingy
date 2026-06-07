import asyncio
import os
import sys
from http.server import BaseHTTPRequestHandler

from vercel.blob import AsyncBlobClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BLOB_PATH = "budget.bin"
BLOB_ACCESS = "private"


async def _load_budget_bin() -> bytes | None:
    client = AsyncBlobClient()
    result = await client.get(BLOB_PATH, access=BLOB_ACCESS)
    if result is None or result.status_code != 200 or result.stream is None:
        return None

    chunks: list[bytes] = []
    async for chunk in result.stream:
        chunks.append(chunk)
    return b"".join(chunks)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            body = asyncio.run(_load_budget_bin())
            if body is None:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"budget.bin has not been generated yet")
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            body = f"ERROR: {exc}".encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

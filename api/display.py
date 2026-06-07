import os
import sys

from vercel.blob import AsyncBlobClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BLOB_PATH = "budget.bin"
BLOB_ACCESS = "private"


async def _load_budget_bin(blob_token: str | None = None) -> bytes | None:
    client = AsyncBlobClient(token=blob_token)
    result = await client.get(BLOB_PATH, access=BLOB_ACCESS)
    if result is None or result.status_code != 200 or result.stream is None:
        return None

    chunks: list[bytes] = []
    async for chunk in result.stream:
        chunks.append(chunk)
    return b"".join(chunks)

from dotenv import load_dotenv
import os

load_dotenv()

API_TOKEN: str = os.environ.get("YNAB_API_TOKEN", "")
BUDGET_ID: str = os.environ.get("YNAB_BUDGET_ID", "")
EXCLUDED_PAYEE_PATTERNS: tuple[str, ...] = tuple(
    pattern.strip().casefold()
    for pattern in os.environ.get("EXCLUDED_PAYEE_PATTERNS", "").split(",")
    if pattern.strip()
)
FLEXIBLE_BUDGET: float = float(os.environ.get("FLEXIBLE_BUDGET", "0"))

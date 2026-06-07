from dotenv import load_dotenv
import os

load_dotenv()

API_TOKEN: str = os.environ.get("YNAB_API_TOKEN", "")
BUDGET_ID: str = os.environ.get("YNAB_BUDGET_ID", "")
FIXED_GROUP_NAME: str = os.environ.get("FIXED_GROUP_NAME", "Fixed")
_DEFAULT_EXCLUDED_GROUPS = f"{FIXED_GROUP_NAME},Internal Master Category,Credit Card Payments"
EXCLUDED_GROUP_NAMES: set[str] = {
    name.strip()
    for name in os.environ.get("EXCLUDED_GROUP_NAMES", _DEFAULT_EXCLUDED_GROUPS).split(",")
    if name.strip()
}
EXCLUDED_PAYEE_PATTERNS: tuple[str, ...] = tuple(
    pattern.strip().casefold()
    for pattern in os.environ.get("EXCLUDED_PAYEE_PATTERNS", "").split(",")
    if pattern.strip()
)
FLEXIBLE_BUDGET: float = float(os.environ.get("FLEXIBLE_BUDGET", "0"))

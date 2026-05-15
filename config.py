from dotenv import load_dotenv
import os

load_dotenv()

API_TOKEN: str = os.environ.get("YNAB_API_TOKEN", "")
BUDGET_ID: str = os.environ.get("YNAB_BUDGET_ID", "")
GROUP_NAME: str = os.environ.get("FLEXIBLE_GROUP_NAME", "Flexible")
FLEXIBLE_BUDGET: float = float(os.environ.get("FLEXIBLE_BUDGET", "0"))

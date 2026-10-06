import logging
import os

from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient

load_dotenv()


# Strategy config
SIGNAL_TICKER: str = "SPY"
RISK_TICKER: str = "SSO"
SAFE_TICKER: str = "BIL"

MA_WINDOW: int = 200
BUFFER_PCT: float = 0.0175


# Enviornment variables
API_KEY  = os.getenv("APCA_API_KEY_ID")
SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

if not API_KEY or not SECRET_KEY:
    raise RuntimeError("Missing Alpaca API key(s) in .env")


# Logging config
class _SessionLogHandler(logging.Handler):
    """Collects formatted log lines emitted during this run, for use in notifications."""

    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Format and store the log record for later retrieval."""
        self.lines.append(self.format(record))


session_log_handler = _SessionLogHandler()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        session_log_handler,
    ],
)
log = logging.getLogger(__name__)


def get_session_log() -> str:
    """Return all log lines emitted so far this run, joined by newlines."""
    return "\n".join(session_log_handler.lines)


# Alpaca client
trading_client = TradingClient(
    api_key=API_KEY,
    secret_key=SECRET_KEY,
    paper=True
)

data_client = StockHistoricalDataClient(
    api_key=API_KEY,
    secret_key=SECRET_KEY,
)
log.info("Alpaca client initialized")
from datetime import datetime
from zoneinfo import ZoneInfo

from alpaca.trading.models import TradeAccount

from config import trading_client


def is_margin_enabled(account: TradeAccount) -> bool:
    """Check if the account is a margin account."""
    return float(account.multiplier) > 1.0


def is_trading_blocked(account: TradeAccount) -> bool:
    """Check if the account is blocked from trading."""
    return bool(account.account_blocked or account.trading_blocked)


def is_market_open() -> bool:
    """Check if market is open or closed."""
    return trading_client.get_clock().is_open


def is_not_404(exception: Exception) -> bool:
    """Returns True to retry, False to stop retrying."""
    return getattr(exception, 'status_code', None) != 404


def in_submission_window() -> bool:
    """Only submit between 7:00pm and 9:28am ET (OPG cutoff is 9:28am)."""
    now = datetime.now(ZoneInfo("America/New_York"))
    return now.hour >= 19 or (now.hour, now.minute) < (9, 28)
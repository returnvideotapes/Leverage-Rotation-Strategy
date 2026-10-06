from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from alpaca.data.requests import StockBarsRequest
from alpaca.common.exceptions import APIError
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment

from tenacity import (
    retry, 
    wait_fixed, 
    stop_after_attempt, 
    retry_if_exception, 
)

from utils.guards import is_not_404
from utils.notify import log_retry

from config import (
    BUFFER_PCT,
    data_client,
    trading_client,
)


@retry(
    before_sleep=log_retry,
    retry=retry_if_exception(is_not_404),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    reraise = True,
)
def get_position_qty(ticker: str) -> int:
    """Current whole-share position in `ticker`, 0 if none held."""
    try:
        qty = trading_client.get_open_position(ticker).qty
    except APIError as e:
        if e.status_code == 404:  # genuinely no position
            return 0
        raise
    return int(float(qty))  # qty comes back as a string; float() first handles any fractional qty


@retry(before_sleep=log_retry, stop=stop_after_attempt(5), wait=wait_fixed(30), reraise=True)
def get_close_price(ticker: str) -> float:
    """Most recent completed daily close - can also fetch intraday price."""
    request = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Day,
        start=datetime.now(ZoneInfo("America/New_York")) - timedelta(days=7),
        adjustment=Adjustment.RAW
    )
    bar_data = data_client.get_stock_bars(request).df
    if bar_data.empty:
        raise ValueError(f"No historical data returned for {ticker}.")

    last_price = float(bar_data.xs(ticker)["close"].iloc[-1])
    if not (last_price > 0):  # `not >` (rather than `<=`) also traps NaN
        raise ValueError(f"Invalid latest close for {ticker}: {last_price}")
    return last_price


def calculate_shares(price: float, cash_available: float) -> int:
    """Whole shares affordable at `price`, holding back `buffer_pct` of cash."""
    if price <= 0:
        raise ValueError(f"Invalid price: {price}")
    usable_cash = cash_available * (1 - BUFFER_PCT)
    return int(usable_cash // price)
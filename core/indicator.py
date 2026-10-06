from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment

from tenacity import retry, wait_fixed, stop_after_attempt

from utils.notify import log_retry

from config import (
    log,
    data_client,
)


@retry(
    before_sleep=log_retry,
    stop=stop_after_attempt(5), 
    wait=wait_fixed(30), 
    reraise=True
)
def get_signal_data(ticker: str, window: int) -> tuple[float, float]:
    """Return (latest_close, sma) for ticker from a single adjusted bar fetch."""
    request = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Day,
        start=datetime.now(ZoneInfo("America/New_York")) \
            - timedelta(days=int(window * 2)),
        adjustment=Adjustment.ALL,  # dividends and splits (mirrors total return index)
    )
    bar_data = data_client.get_stock_bars(request).df
    if bar_data.empty:
        raise ValueError(f"No historical data returned for {ticker}.")
 
    closes = bar_data.xs(ticker)["close"]
    
    if not closes.index.is_monotonic_increasing or closes.index.has_duplicates:
        raise ValueError(f"Bars for {ticker} out of order or duplicated.")
    if len(closes) < window:
        raise ValueError(f"Only {len(closes)} bars returned for {ticker}, need {window}.")

    # Validate exactly the bars the signal uses (last `window`): a NaN here silently forces risk-off.
    used = closes.iloc[-window:]
    if used.isna().any() or (used <= 0).any():
        raise ValueError(f"Bad bars for {ticker}: NaN or non-positive close in SMA window.")
 
    latest_close = float(closes.iloc[-1])
    sma = float(closes.rolling(window).mean().iloc[-1])
    return latest_close, sma


def determine_regime(ticker: str, window: int) -> bool:
    """Determines the market regime based on a Simple Moving Average (SMA)"""
    signal_price, sma = get_signal_data(ticker, window)
    log.info(
        f"{ticker} adjusted close={signal_price:.2f}, "
        f"{window}-day SMA={sma:.2f}"
    )
    
    return signal_price > sma
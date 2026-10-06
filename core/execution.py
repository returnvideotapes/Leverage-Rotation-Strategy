from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from tenacity import (
    retry, 
    wait_fixed, 
    stop_after_attempt, 
    retry_if_not_exception_type, 
)

from utils.notify import log_retry

from config import (
    log,
    trading_client,
)


@retry(
    before_sleep=log_retry,
    retry=retry_if_not_exception_type(RuntimeError),
    stop=stop_after_attempt(2), 
    wait=wait_fixed(20), 
    reraise=True,
)
def check_open_orders(ticker: str) -> None:
    """Check if there are any open orders for the given ticker."""
    open_orders = len(trading_client.get_orders())
    if open_orders > 0:
        raise RuntimeError(f"Cannot submit order for {ticker}: {open_orders} existing open order/s detected.")
    log.info("No existing open order/s detected.")


@retry(
    before_sleep=log_retry,
    stop=stop_after_attempt(3), 
    wait = wait_fixed(90),
    reraise=True,
)
def submit_order(ticker: str, shares: int, side: OrderSide, tif: TimeInForce) -> None:
    """Submit an order to Alpaca."""
    check_open_orders(ticker) # Checks ALL existing open orders - not just ticker

    verb = "Buying" if side == OrderSide.BUY else "Selling"
    log.info("%s %s shares of %s", verb, shares, ticker)

    order_request = MarketOrderRequest(
        symbol=ticker,
        qty=shares,
        side=side,
        type=OrderType.MARKET,
        time_in_force=tif,
    )
    try:
        order = trading_client.submit_order(order_data=order_request)
    except Exception as e:
        raise RuntimeError(f"Order submission failed for {ticker}: {e}") from e

    log.info("%s order %s submitted, status=%s", tif.value.upper(), order.id, order.status)
    #return order
from alpaca.trading.enums import TimeInForce, OrderSide
from alpaca.trading.models import TradeAccount

from tenacity import (
    retry, 
    wait_fixed, 
    stop_after_attempt, 
    retry_if_not_exception_type
)

from core.indicator import determine_regime
from core.execution import submit_order
from utils.notify import log_retry

from utils.market import (
    get_close_price,
    get_position_qty, 
    calculate_shares,
)

from utils.guards import (
    is_market_open, 
    is_margin_enabled,
    is_trading_blocked, 
    in_submission_window,
)

from config import (
    log, 
    MA_WINDOW, 
    BUFFER_PCT,
    RISK_TICKER, 
    SAFE_TICKER,
    SIGNAL_TICKER, 
    trading_client,
)


@retry(
    before_sleep=log_retry,
    stop=stop_after_attempt(3), 
    wait=wait_fixed(2), 
    reraise=True
)
def account() -> TradeAccount:
    """Refresh and return the account object from Alpaca."""
    return trading_client.get_account()


@retry(
    before_sleep=log_retry,
    retry=retry_if_not_exception_type(RuntimeError),
    stop=stop_after_attempt(3), 
    wait=wait_fixed(2), 
    reraise=True,
)
def check_account_status(account: TradeAccount) -> None:
    """Check if the account is a margin account and not blocked from trading."""
    if is_margin_enabled(account):
        raise RuntimeError("Account has margin enabled")
    if is_trading_blocked(account):
        raise RuntimeError("Blocked from trading")


def strategy() -> str:
    """Main trading logic - rotate in/out of assets. Returns a summary of the action taken."""
    check_account_status(account())

    # Check if market is open OR inside the submission window
    if is_market_open() or not in_submission_window():
        raise RuntimeError("Market is open or not in submission window.")
    log.info("Market is closed and safe: running strategy")

    risk_on = determine_regime(SIGNAL_TICKER, MA_WINDOW)
    target = RISK_TICKER if risk_on else SAFE_TICKER
    source = SAFE_TICKER if risk_on else RISK_TICKER
    
    risk_label = "ON" if risk_on else "OFF"
    log.info("Risk: %s", risk_label)

    held_source = get_position_qty(source)
    held_target = get_position_qty(target)

    log.info(
        "Holding %s x%s, %s x%s",
        source,
        held_source,
        target,
        held_target,
    )

    idle_cash = float(account().buying_power)
    if (held_source == 0) and (held_target > 0):
        portfolio_value = float(account().portfolio_value)

        if idle_cash < portfolio_value * (BUFFER_PCT + 0.005):
            log.info(
                "Already invested in %s (%s shares) and cash is below buffer.",
                target,
                held_target,
            )
            return f"Risk {risk_label}: Holding {target} x{held_target}, no rebalance needed."
        log.info("Already in %s but $%.2f idle cash; rebalancing.", target, idle_cash)

    # Sell current holding if necessary
    if held_source > 0:
        submit_order(source, held_source, OrderSide.SELL, TimeInForce.OPG)
        summary = f"Risk {risk_label}: Selling {held_source} shares of {source} at next open."
    else:
        target_price = get_close_price(target)
        target_shares = calculate_shares(target_price, idle_cash) # Reuse idle_cash; virtually no delay
        log.info("%s last close=%.2f, target shares=%s", target, target_price, target_shares)
        
        if target_shares <= 0:
            log.info(
                "Idle cash $%.2f insufficient to buy 1 share of %s at $%.2f; skipping.",
                idle_cash, target, target_price,
            )
            return f"Risk {risk_label}: Holding {target} x{held_target}, idle cash (${idle_cash:.2f}) too small to add shares."

        submit_order(target, target_shares, OrderSide.BUY, TimeInForce.OPG)
        summary = f"Risk {risk_label}: Buying {target_shares} shares of {target} at next open."

    log.info("Order routine complete")
    return summary
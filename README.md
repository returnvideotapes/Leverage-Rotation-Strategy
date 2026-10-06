# Leverage Rotation Strategy: Live Implementation

A stateless, scheduled Python implementation of the 200-day moving-average Leverage Rotation Strategy (LRS) from Michael A. Gayed's *Leverage for the Long Run*. It trades a leveraged S&P 500 ETF and a T-bill ETF through the Alpaca API and runs as a container on Google Cloud.

> Educational project. Not investment advice and not intended for trading. The strategy's reported edge is not statistically significant, as the paper's own 2026 revision shows (see [Research findings](#research-findings)).

## Contents

- [Overview](#overview)
- [Strategy](#strategy)
- [Backtest vs. live trading](#backtest-vs-live-trading)
- [Architecture](#architecture)
- [Implementation notes](#implementation-notes)
- [Project structure](#project-structure)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Operations](#operations)
- [Research findings](#research-findings)
- [Authorship](#authorship)

## Overview

This project was built to study the gap between a backtest and a live trading system. The backtest of a moving-average rotation is a few lines of pandas: compute a signal, shift it one row, multiply returns. A live system also has to decide when the signal is actually known, what price an order gets, where cash sits between trades, and how to recover from rejected orders, incomplete data, outages and market holidays. The strategy is deliberately simple so that the engineering is about execution, not about the signal.

Once per weekday evening the job reads SPY's final daily close, evaluates the regime, reconciles it against the account's positions, and submits at most one market-on-open (OPG) order for the next session. With $P_t$ the dividend- and split-adjusted close on session $t$:

$$
S_t^{(N)} = \frac{1}{N}\sum_{i=0}^{N-1} P_{t-i},
\qquad
\rho_t = \mathbf{1}\left\lbrace P_t > S_t^{(N)} \right\rbrace,
\qquad
N = 200
$$

$\rho_t = 1$ selects the risk-on ETF and $\rho_t = 0$ the risk-off ETF, so equality resolves to risk off.

| Regime | Position | Configured ticker |
|---|---|---|
| $\rho_t = 1$ | Daily-reset leveraged S&P 500 ETF | `RISK_TICKER` (deployed: SSO, 2x; UPRO, 3x, is the paper's other ETF case) |
| $\rho_t = 0$ | 1–3 month Treasury bills | `SAFE_TICKER` (BIL) |

The job keeps no state between runs, never polls for fills, and derives every action from the signal, current positions and current cash. A missed or failed action is therefore corrected by the next run.

## Strategy

### Research basis

The implementation is modeled on the 2020 edition of *Leverage for the Long Run: A Systematic Approach to Managing Risk and Magnifying Returns in Stocks* (Gayed, updated through December 31, 2020; 2016 Charles H. Dow Award, with Charles Bilello; [SSRN 2741701](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2741701)). The rule as published:

> When the S&P 500 Index closes above its Moving Average, rotate into the S&P 500 and use leverage to magnify returns. When the S&P 500 Index closes below its Moving Average, rotate into Treasury bills to manage risk.

The paper argues that volatility, not holding period, is what erodes daily-reset leverage, and that the 200-day moving average separates low-volatility, trending regimes from high-volatility, choppy ones. Its modern-day implementation tests SSO (2x) and UPRO (3x). In September 2026 the author published Research Revision P4, which re-tests the strategy with costs, financing, significance tests and a disclosed parameter grid. Where the 2020 edition is ambiguous, the table below follows the revision.

### Alignment with the paper

| Element | Paper | This implementation |
|---|---|---|
| Signal series | S&P 500 total-return index; the moving average uses total-return closes (2020 edition, footnotes 15–16) | SPY with `Adjustment.ALL` (splits and dividends) as a tradable total-return proxy |
| Moving average | 2020 edition: "unweighted mean of the prior n days." Revision: latest 200 closes, including the signal date | `closes.rolling(200).mean().iloc[-1]`, which includes the latest close |
| Comparison | Revision: strictly higher selects leverage; equality or lower selects cash | `signal_price > sma` |
| Window | 200 days | `MA_WINDOW = 200` |
| Leverage | 1.25x, 2x and 3x daily re-leveraging; ETF implementation via SSO (2x) or UPRO (3x) | `RISK_TICKER`, deployed as SSO |
| Risk-off asset | T-bills; the 2020 edition's ETF tables hold cash, the revision's use BIL | `SAFE_TICKER = "BIL"` |
| Leverage cost | 2020 edition: 1% annual fee. Revision: fee plus financing spread | Embedded in the ETF's NAV; the account never borrows |
| Rotation frequency | About 5 per year at 200 days | Same signal; each rotation is two orders |
| Execution | Same-day close, one-row shift | Verified close, next opening auction |

### Execution timing

The 2020 edition states the rule on the close but not when the trade executes. The revision makes the convention explicit: each close's signal earns the next close-to-close return, a one-row shift ("a position selected for Friday's close first earns the Friday-close-to-Monday-close return"). The revision calls this same-day-close execution and identifies it as the original assumption. Earning the return from close $t$ requires holding the new position at close $t$, so it assumes a signal observed before the market-on-close order cutoff is unchanged at the final print, an assumption the revision states it cannot verify.

This implementation reads the verified final close and executes at the next opening auction. Exits from the risk-on ETF fill at open $t+1$; entries into it fill at open $t+2$ because of the [two-step rotation](#two-step-rotation).

The execution delay is accepted by design. For a linear trend $P_t = \alpha + \beta t$, the moving average is

$$
S_t^{(N)} = \alpha + \beta\left(t - \frac{N-1}{2}\right) = P_{\,t-(N-1)/2},
$$

so the signal already trails price by $(N-1)/2 = 99.5$ sessions at $N = 200$. Any choice of $N$ builds in a delay that dwarfs one or two sessions of execution latency. The revision's own delay tests on actual SSO/BIL returns show no systematic penalty:

| Execution delay | 2007–2026 CAGR | Max drawdown | 2021–2026 CAGR | Max drawdown |
|---|---|---|---|---|
| 1 session (paper's convention) | 13.72% | −38.23% | 19.23% | −37.35% |
| 2 sessions | 11.63% | −43.61% | 15.91% | −43.13% |
| 3 sessions | 11.24% | −41.18% | 14.92% | −41.18% |
| 5 sessions | 13.69% | −38.43% | 20.31% | −30.32% |

The 1- and 5-session results are nearly identical over 2007–2026. The spread between delays is non-monotone, and the revision attributes it to a few transition dates (avoiding a bad return or missing a recovery) rather than to a cost that grows with delay. This project's own delay testing reached the same conclusion. The 2- and 3-session results were lower in these samples, and that dispersion should be read as path sensitivity, not as a reason to pick a timing after the fact. Given that timing is noise at the resolution of a few sessions, the execution format was chosen for robustness: a verified signal, one order per run, and the opening auction.

## Backtest vs. live trading

| Backtest assumption | Live constraint | Handling |
|---|---|---|
| Signal known and filled at the same close | The close is final only after 4:00 pm; free data blocks the latest 15 minutes of consolidated prints | Read the final bar hours later; execute at the next open |
| Fill at a known price | OPG fills at the auction price, unknown at sizing time | Size from the last close with a 1.75% cash buffer |
| Continuous, fully invested positions | OPG orders accept whole shares only | Floor to whole shares; tolerate small idle cash |
| Instantaneous rotation | In a cash account, sale proceeds exist only after the sale fills | Sell at one open, buy at the next |
| Dividends reinvested in the total-return series | Distributions arrive as cash | Sweep idle cash into the target above a threshold |
| Every trade executes | Orders can be rejected, canceled, expired or partially filled; APIs time out | Stateless reconciliation, retries, open-order check |
| Leverage is $L\,r_t$ less a fee | Leverage comes from a daily-reset ETF; margin would add a second layer | Hold the ETF; refuse margin accounts |
| Costs are fixed basis points | Auction prices, spreads, regulatory fees | Commission-free broker, auction execution |
| Clean data | Bars can be missing, duplicated, out of order or NaN; a NaN silently forces risk off | Validate every bar the signal uses |
| Dates are a list | Holidays, DST, broker order-acceptance windows | UTC schedule, submission-window guard, broker clock |
| Runs once, on demand | Needs scheduling, failure handling and reporting | Container, scheduler, timeout, task retry, email with full log |

## Architecture

### Schedule

The job is started by an external cron trigger. Any schedule works if it fires once per trading-day evening, after the close and inside the OPG window (7:00 pm–9:28 am ET). The reference schedule is `0 2 * * 2-6` in UTC: 02:00 UTC Tuesday through Saturday is Monday through Friday evening in New York, 10:00 pm ET under daylight time and 9:00 pm ET under standard time. Both fall inside the window, so the schedule needs no DST adjustment.

### Run sequence

```
main.run()
 └─ engine.strategy()
     1. account()                        fetch account
     2. check_account_status()           refuse margin-enabled or blocked accounts
     3. is_market_open()
        in_submission_window()           require market closed and 7:00 pm–9:28 am ET
     4. determine_regime("SPY", 200)     adjusted close vs. 200-day SMA
     5. target, source                   risk on:  target RISK_TICKER, source SAFE_TICKER
                                         risk off: target SAFE_TICKER, source RISK_TICKER
     6. get_position_qty(source, target)
     7. one branch:
        a. only target held, idle cash < 2.25% of portfolio  → no order
        b. any source held                                   → OPG sell of all source shares
        c. otherwise                                         → OPG buy of target, sized from last close
                                                               (skipped if under one share)
 └─ notify()                             email summary and session log
```

### Rotation timeline

| Time | Event |
|---|---|
| Day $t$, 4:00 pm | SPY closes below its 200-day SMA |
| Night $t$ | Risk off, leveraged ETF held → OPG sell |
| Day $t+1$, 9:30 am | Sold in the opening auction; account in cash |
| Night $t+1$ | Risk off, nothing held → OPG buy of BIL |
| Day $t+2$, 9:30 am | BIL bought; rotation complete |
| Later nights | Target held, cash below threshold → no order |

## Implementation notes

### Signal

`get_signal_data()` requests daily SPY bars with `Adjustment.ALL`, which folds distributions back into the price history and yields a total-return series as the paper specifies. A price-only series would drop against its average on each ex-dividend date and could flip on a distribution rather than on trend. The request spans `window * 2` calendar days (400), about 275 sessions, to guarantee at least 200. The latest close is included in the average and the comparison is strict, matching the revision.

### Two-step rotation

Completing a rotation within one session requires one of four designs, each less robust:

1. Sell at the open and buy once the sale fills. The buy lands in the opening range, the most volatile minutes of the session, which a leveraged ETF amplifies. It also requires a process alive through the open, polling for the fill.
2. Sell at the open and buy market-on-close. This avoids the opening range but requires confirming the sale and submitting before the closing-auction cutoff: polling, or a second scheduled run near the close.
3. Enter shortly before the close on the expected signal. This trades on a forecast of the close rather than the close itself: the final minutes can carry the price across the average, leaving a position the confirmed signal does not support. It also requires real-time consolidated data, which the free plan does not provide.
4. Special-case the T-bill leg. An intraday BIL entry is harmless in price terms, since BIL has no meaningful opening range, but it adds a second execution path with its own timing and polling in exchange for one session of T-bill yield.

With one OPG order per nightly run, every order follows the same path, at the same time, through the opening auction's single cross price. The design also fits a cash account: at the time of the nightly run the sale has not occurred, so its proceeds are not in buying power. Proceeds from the sale at open $t+1$ settle on $t+2$ (T+1), the buy's trade date, so the rotation never depends on unsettled funds.

### Market data

Alpaca combines a commission-free brokerage API, OPG support and market data under one key. The free Basic plan cannot query consolidated (SIP) data from the most recent 15 minutes ([Alpaca market data FAQ](https://docs.alpaca.markets/docs/market-data-faq)). The bars endpoint defaults to SIP, and on the free plan an omitted `end` defaults to 15 minutes before the current time. The requests deliberately set neither `feed` nor `end`. At 9–10 pm ET that cutoff falls hours after the 4:00 pm close, so the returned daily bars are complete full-market SIP data, identical to the paid plan. Acting on a pre-close signal would require real-time consolidated data and a paid plan.

SPY is the signal series because Alpaca provides no index data and SPY is the most liquid and tightly tracking S&P 500 proxy; its expense ratio is immaterial to a 200-day trend comparison.

### Submission window

Alpaca [accepts OPG orders](https://docs.alpaca.markets/docs/orders-at-alpaca) only between 7:00 pm and 9:28 am ET. `in_submission_window()` mirrors that rule so the job never runs when its order would be rejected. `is_market_open()` adds an independent check against Alpaca's holiday-aware clock.

### Sizing, buffer and cash sweep

`BUFFER_PCT` is an execution buffer, not a signal filter; the revision cautions that signal buffers and confirmation delays amount to optimization. OPG orders are sized from the last close but fill at the next open, which can gap higher. With buying power $C$, the target's last close $\hat{P}$ (standing in for the unknown opening fill price), portfolio value $V$ and $b = 0.0175$:

$$
q = \left\lfloor \frac{(1-b)\,C}{\hat{P}} \right\rfloor,
\qquad
\text{top up only if } C \ge (b + 0.005)\,V
$$

Shares are whole because Alpaca accepts fractional quantities only on DAY orders. A 3x risk-on ETF has larger overnight gaps, and $b$ should be revisited if `RISK_TICKER` is changed.

The top-up rule applies only when the target alone is held. A full deployment, either the first buy or the buy leg of a rotation, leaves roughly $b$ of the account in cash plus any whole-share remainder. A top-up applies the buffer only to the idle cash being deployed, so the residual after a top-up is negligible. The additional 0.5% threshold acts as hysteresis: it keeps the normal residual from a full deployment, rounding and small distributions from triggering an order every night, while larger balances from distributions (BIL monthly, the leveraged ETF periodically) or deposits are swept into the target once the threshold is exceeded. A fill below the sizing price leaves more cash behind; a gap down of about 0.5% or more on the buy can push the residual over the threshold and trigger a single top-up the following night. If the threshold is met but $q = 0$, the run skips rather than submit a zero-share order, which Alpaca rejects.

### Account guards

`is_margin_enabled()` refuses accounts with `multiplier > 1`. Sizing treats `buying_power` as cash; in a margin account it is 2x or 4x equity, which would silently lever an already-levered ETF. All leverage must come from the ETF. `is_trading_blocked()` refuses blocked accounts. Guard failures raise `RuntimeError`, which the retry policies exclude, so refusals are immediate.

### Order safety

`submit_order()` calls `check_open_orders()` before every attempt and refuses if any order is open on the account. Because the account runs one strategy, an open order means an action is already in flight. The check doubles as duplicate protection: if an order is accepted but the response is lost, the next attempt fires 90 seconds later, finds the now-visible order and refuses, so the run ends in an error rather than a duplicate. The 90-second wait gives the order list time to reflect a submission that failed client-side. The same property makes a full task retry safe.

### Data validation

`get_signal_data()` rejects empty responses, out-of-order or duplicated bars, fewer than 200 bars, and any NaN or non-positive close in the 200 bars used; a NaN would make the comparison evaluate `False` and force risk off. `get_close_price()` uses `Adjustment.RAW` because sizing needs the traded price, looks back 7 days to span weekends and holiday closures, and rejects NaN and non-positive values with `not (x > 0)`. `get_position_qty()` treats only HTTP 404 as a flat position; any other error is retried and raised, since reporting an unverified flat position could trigger a buy while the source is still held.

### Retry policy

| Function | Attempts | Wait | Not retried on | Reason |
|---|---|---|---|---|
| `account()` | 3 | 2 s | — | Read-only |
| `check_account_status()` | 3 | 2 s | `RuntimeError` | Guard failures are final |
| `get_signal_data()` | 5 | 30 s | — | Data read |
| `get_close_price()` | 5 | 30 s | — | Data read |
| `get_position_qty()` | 3 | 2 s | HTTP 404 | 404 is handled as no position |
| `check_open_orders()` | 2 | 20 s | `RuntimeError` | An open order is a real state |
| `submit_order()` | 3 | 90 s | — | Lets a lost order surface so later attempts refuse |
| `send_email()` | 3 | 10 s | — | Transient SMTP failures |

Retries are logged through `log_retry()` and appear in the emailed session log. The longest single budget is order submission: two 90-second waits plus up to three 20-second open-order-check waits, 4 minutes in total. A failure in any one dependency therefore resolves inside the 6-minute task timeout. Only a compound failure, several services failing repeatedly in the same run, can exceed it; the timeout then ends the task and the task retry reruns it, which the open-order check makes safe.

### Failure handling and logging

`config.py` configures two handlers: a `StreamHandler` to stdout, captured by Cloud Logging, and `_SessionLogHandler`, which buffers the run's lines for the email. `main.run()` sends `[Strategy] UPDATE` on success or `[Strategy] ERROR` on failure, each with the session log. On failure it re-raises, the process exits non-zero, and Cloud Run marks the task failed and retries it once. An email failure after a successful trade is logged and does not fail the run.

Email uses Gmail SMTP over SSL with an app password and is skipped with a warning when unconfigured. Every message is sent from and to the configured address with a `[Strategy]` subject prefix, so a single mail filter on that prefix can route the daily reports to a dedicated folder or label.

## Project structure

```
.
├── config.py            strategy constants, environment, logging, shared Alpaca clients
├── main.py              entry point: run the strategy, email the result
├── requirements.txt
├── Dockerfile
├── .dockerignore
├── core/
│   ├── engine.py        orchestration: guards → signal → decision → order
│   ├── execution.py     open-order check, OPG market order submission
│   └── indicator.py     adjusted bars → (close, SMA) → regime
└── utils/
    ├── guards.py        margin, blocked, market clock, submission window
    ├── market.py        positions, last raw close, share sizing
    └── notify.py        Gmail SMTP email, retry logging
```

`core/engine.py` is the only module that sequences steps; `strategy()` returns a one-line summary used as the email body. `utils/guards.py` holds pure predicates plus `is_not_404()`, the retry filter for position lookups. All modules import the shared `log`, `trading_client` and `data_client` from `config.py`, so clients and logging are created once per run.

## Configuration

| Constant | Value | Meaning |
|---|---|---|
| `SIGNAL_TICKER` | `"SPY"` | Signal series |
| `RISK_TICKER` | `"SSO"` | Risk-on ETF (UPRO for 3x) |
| `SAFE_TICKER` | `"BIL"` | Risk-off ETF |
| `MA_WINDOW` | `200` | SMA length in sessions (the paper's declared specification) |
| `BUFFER_PCT` | `0.0175` | Cash held back when sizing; the top-up threshold is this + 0.005 |

The trading client is created with `paper=True`, so the environment must hold the paper account's API key pair; paper and live accounts use separate keys. Do not use on live accounts. Alpaca paper accounts default to a maximum margin multiplier of 4, which the margin guard refuses, so set the paper account's maximum margin multiplier to 1 (in the paper account settings, or `max_margin_multiplier` through the account configurations endpoint) before the first run.

| Environment variable | Required | Purpose |
|---|---|---|
| `APCA_API_KEY_ID` | Yes | Alpaca API key |
| `APCA_API_SECRET_KEY` | Yes | Alpaca API secret |
| `EMAIL_ADDRESS` | No | Gmail sender and recipient |
| `EMAIL_APP_PASSWORD` | No | Gmail app password |

In deployment the variables are supplied by the Cloud Run runtime. For local development, `load_dotenv()` reads a `.env` file in the project root and does nothing when none exists; `.env` is excluded from the image. Missing Alpaca keys stop the job at import.

## Deployment

The image is pushed to Google Artifact Registry and executed as a Cloud Run job by a Cloud Scheduler cron trigger. Each execution starts a fresh container; nothing persists between runs except the account state at the broker.

| Cloud Run setting | Value | Rationale |
|---|---|---|
| Task timeout | 6 minutes | Covers the longest single retry budget (4 minutes) and bounds hung connections |
| Retries per failed task | 1 | Safe because runs are stateless and duplicate orders are blocked |

```dockerfile
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY core/ ./core/
COPY utils/ ./utils/
COPY config.py .
COPY main.py .
CMD ["python", "main.py"]
```

Dependencies are copied before code so the dependency layer caches across code changes. Only runtime code is copied. `PYTHONUNBUFFERED` flushes logs to Cloud Logging immediately; `PYTHONDONTWRITEBYTECODE` keeps `.pyc` files out of the image. `CMD` runs one pass and exits; the scheduler provides the loop.

| Package | Purpose |
|---|---|
| `alpaca-py==0.43.5` | Trading and market data clients |
| `python-dotenv==1.2.3` | Optional local `.env` loading |
| `tzdata==2025.2` | IANA time zone data for `zoneinfo`, independent of the host; required on Windows and on images without a system time zone database |
| `tenacity==9.1.4` | Retry decorators |

`.dockerignore` excludes `.git`, `.gitignore`, `.env`, `.venv`, `venv`, and recursively `__pycache__`, `*.pyc`, `*.pyo`, `*.log`, `logs` and `*.md`. Recursive patterns use the `**/` prefix because a bare pattern in `.dockerignore`, unlike `.gitignore`, matches only at the build-context root. Excluding `.env` keeps secrets out of the image.

## Operations

| Situation | Behavior |
|---|---|
| Signal unchanged, fully invested | No order |
| Fresh all-cash account | Buys the current target |
| OPG order rejected, canceled or expired | Positions unchanged; the next run reissues it |
| Partial fill | The next run trades the remainder |
| Signal reverses before the buy leg | The next run buys the new target |
| Distributions or deposits reach 2.25% of portfolio | Swept into the target at the next open |
| Idle cash over threshold but under one share | Logged and skipped |
| Run started during market hours or 9:28 am–7:00 pm ET | Refused |
| Margin enabled or account blocked | Refused |
| Data API outage | Retried, then ERROR; the task retries once; the next night proceeds normally |
| Order accepted but response lost, or task fails after submitting | Later attempts find the open order and refuse |
| Task exceeds the timeout | Terminated without an email; the task retry runs and reports |
| Email fails after a successful order | Logged; run succeeds |
| Missing Alpaca keys | Fails at import, before the email path exists; visible only in Cloud Logging |

A persistent failure produces two ERROR emails per night, one per attempt.

Known limitations:

- Idle cash can build to just under 2.25% of the portfolio before it is swept, and the account is in cash for one session per rotation.
- A rotation order that spans a market holiday is still queued on the holiday-night run. Nothing is placed and the order fills at the next open, but the open-order check can report a false ERROR, repeated once by the task retry: always for a queued sell, and for a queued buy when the account exceeds roughly 58 times the target's share price.
- Fractional share remnants are ignored (`int(float(qty))`).
- The open-order check is account-wide, so the account must run only this strategy.
- There is no external heartbeat; if the container never starts, no email is sent.
- SMTP connections use the library's default timeout, so a hung mail server is bounded only by the task timeout.

## Research findings

The 2020 edition of the paper was this project's research reference. It states that the results are "robust to various leverage amounts, Moving Average time periods, and across multiple economic and financial market cycles," and reports for 1928–2020 a 2x LRS annual return of 19.0% against 9.4% for the S&P 500, a Sharpe ratio of 0.61 against 0.32, and 11.0% annual alpha.

### Grid search

The project began with a single grid search over moving-average length and leverage instead of accepting the 200-day window as given. The leveraged result did not hold across lengths; it depended on the 200-day choice. A result that exists at one value of a free parameter, fixed after observing the sample, is the signature of an overfitted backtest, and it is why this project is framed as a study of live implementation rather than a strategy to trade.

### Confirmation in the 2026 revision

The author's September 2026 revision reports the same result with its own disclosed grid (2x leverage, 1% financing spread, 1988-10-17 to 2026-08-31):

| MA length | CAGR | Sharpe | Max drawdown |
|---|---|---|---|
| 10 | 0.19% | −0.01 | −91.35% |
| 20 | 2.72% | 0.10 | −84.56% |
| 50 | 5.90% | 0.24 | −70.17% |
| 100 | 9.33% | 0.38 | −78.66% |
| 200 | 14.00% | 0.55 | −46.51% |
| S&P 500 TR | 11.45% | 0.54 | −55.25% |

The dependence holds without leverage as well. The 2020 edition's Table 6 reports 5.2% to 6.4% annual alpha for unleveraged timing at every length from 10 to 200 days; the revision's unleveraged grid ranges from 2.83% CAGR and a 0.05 Sharpe at 10 days to 9.92% and 0.62 at 200.

The headline claims shrink accordingly. Samples differ (the 2020 edition starts in 1928; the revision's principal study starts in 1988 and states that an exact 1928 S&P 500 replication was not established), so this compares claims rather than identical tests:

| Claim | 2020 edition (1928–2020) | 2026 revision (1988–2026) |
|---|---|---|
| 2x LRS vs. S&P 500 annual return | 19.0% vs. 9.4% | 14.00% vs. 11.45% |
| 2x LRS vs. S&P 500 Sharpe | 0.61 vs. 0.32 | 0.55 vs. 0.54 |
| Annual alpha | 11.0% | 4.70% (HAC p = 0.093; Holm-adjusted p = 0.373) |
| Outperformance in rolling 3-year windows | 80% | 67.80% of overlapping 756-session windows |
| Robust across MA lengths | Claimed | Not supported |

The block-bootstrap 95% interval for the annual return difference against the S&P 500 TR is −2.52% to 7.97%. For the actual SSO/BIL implementation (2007–2026), all six relative-growth bootstrap intervals, against SPY and against buy-and-hold SSO, include zero, and excluding 2008 alone reduces relative growth against SPY from +2.56 to +0.16 annualized log points. After the 2020 edition's cutoff (January 2021 to August 2026), 2x rotation returned 18.76% with a Sharpe of 0.72 and a −37.54% maximum drawdown, against 15.12%, 0.74 and −24.49% for the S&P 500 TR. The revision also corrects the 2020 edition's streak argument: under constant frictionless daily leverage, reordering the same daily returns leaves terminal wealth unchanged, so streaks alone are not a source of higher leveraged growth.

What survives is drawdown control relative to permanent leverage: over 1988–2026, 2x constant leverage reached −88.75% at its maximum drawdown against −46.51% for 2x rotation. That is a risk-management property, not evidence of a return edge. The implementation keeps the paper's declared specification (200 sessions, daily-reset leveraged ETF, T-bills) to implement the published rule faithfully; the 200-day window is neither optimized nor validated.

## Authorship

This README and the docstrings in the code were generated with AI assistance. The code itself is entirely my own, and every part of it was deliberately designed and structured for robustness. For educational purposes only; not investment advice.

Last updated: October 6, 2026

from core.engine import strategy
from utils.notify import send_email
from config import get_session_log, log


def notify(subject: str, summary: str) -> None:
    """Email `summary` plus the accumulated session log."""
    send_email(subject, f"{summary}\n\nSession Log:\n{get_session_log()}")


def run() -> None:
    """Run the strategy once and notify on success or failure."""
    try:
        summary = strategy()
    except Exception as e:
        try:
            notify("[Strategy] ERROR", str(e))
        except Exception:
            log.exception("Failed to send error notification email.")
        raise

    try:
        notify("[Strategy] UPDATE", summary)
    except Exception:
        log.exception("Trade succeeded but notification email failed.")


if __name__ == "__main__":
    run()
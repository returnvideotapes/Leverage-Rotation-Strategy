import smtplib
from email.message import EmailMessage

from tenacity import retry, wait_fixed, stop_after_attempt

from config import (
    log, 
    EMAIL_ADDRESS, 
    EMAIL_APP_PASSWORD, 
)


def log_retry(retry_state):
    """Route Tenacity data to logs."""
    log.warning(f"Attempt {retry_state.attempt_number} failed. Retrying...")


@retry(before_sleep=log_retry, stop=stop_after_attempt(3), wait=wait_fixed(10), reraise=True)
def send_email(subject: str, body: str) -> None:
    """Send a plain-text status email via Gmail SMTP."""
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        log.warning("Email not configured (EMAIL_ADDRESS/EMAIL_APP_PASSWORD), skipping notification.")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)

    log.info("Notification email sent to %s", EMAIL_ADDRESS)
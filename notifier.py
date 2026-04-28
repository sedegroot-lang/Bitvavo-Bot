import smtplib
from email.mime.text import MIMEText
import os
import logging
from dotenv import load_dotenv

load_dotenv()
EMAIL_HOST = os.getenv('EMAIL_HOST')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USER = os.getenv('EMAIL_USER')
EMAIL_PASS = os.getenv('EMAIL_PASS')
EMAIL_TO = os.getenv('EMAIL_TO')

logger = logging.getLogger(__name__)


def send_email(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_TO
    with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_TO, msg.as_string())


def send_telegram(text: str) -> bool:
    """Stuur een Telegram-notificatie via modules.telegram_handler.

    Gebruikt send_message direct (niet notify) zodat ALLE berichten doorkomen.
    notify() filtert op trade/alert keywords — niet bruikbaar voor algemene
    status/update berichten.

    Roept _reload_credentials() aan zodat standalone scripts (zonder init())
    ook credentials uit config/env hebben.
    """
    try:
        from modules.telegram_handler import send_message, _reload_credentials
        _reload_credentials()
        return bool(send_message(text))
    except Exception as e:
        logger.warning(f"[Notifier] Telegram melding mislukt: {e}")
        return False


def notify(subject: str, body: str = "", level: str = "info") -> None:
    """Gecombineerde notificatie: Telegram (primair), email (optioneel)."""
    emoji = {"info": "ℹ️", "warning": "⚠️", "error": "🔴", "success": "✅"}.get(level, "ℹ️")
    text = f"{emoji} <b>{subject}</b>"
    if body:
        text += f"\n{body}"
    send_telegram(text)

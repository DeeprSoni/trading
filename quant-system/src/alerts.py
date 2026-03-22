"""
Telegram alert system — 3 urgency levels for trade signals.

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)


class TelegramAlerter:
    """Send trading alerts via Telegram Bot API."""

    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send_immediate(self, message: str) -> bool:
        """Fire immediately — stop loss hit, position breached."""
        return self._send(f"\U0001f6a8 IMMEDIATE ACTION\n{message}")

    def send_today(self, message: str) -> bool:
        """Morning signal — entry/exit for today."""
        return self._send(f"\U0001f4cb TODAY SIGNAL\n{message}")

    def send_monitor(self, message: str) -> bool:
        """EOD summary — position at 50% profit, watch tomorrow."""
        return self._send(f"\U0001f440 MONITOR\n{message}")

    def send_raw(self, text: str) -> bool:
        """Send a custom message with no prefix."""
        return self._send(text)

    def _send(self, text: str) -> bool:
        if not self.is_configured:
            logger.warning("Telegram not configured (missing token or chat_id)")
            return False

        try:
            resp = requests.post(
                self.BASE_URL.format(token=self.token),
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info("Telegram alert sent successfully")
                return True
            else:
                logger.warning("Telegram API error: %s %s", resp.status_code, resp.text[:200])
                return False
        except Exception as exc:
            logger.error("Telegram send failed: %s", exc)
            return False

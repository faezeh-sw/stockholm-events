from __future__ import annotations

import logging
import os
import time

import requests

log = logging.getLogger(__name__)


class TelegramError(RuntimeError):
    pass


class Telegram:
    def __init__(self, token: str, chat_id: str, thread_id: int | None = None):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id
        self.thread_id = thread_id      # forum topic inside a group, if any

    @classmethod
    def from_env(cls, admin: bool = False, test: bool = False, audience: str | None = None) -> "Telegram":
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        thread = None
        if admin:
            chat = os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
        elif test:
            chat = os.environ.get("TELEGRAM_TEST_CHANNEL_ID") or os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
        elif os.environ.get("TELEGRAM_GROUP_ID"):
            chat = os.environ["TELEGRAM_GROUP_ID"]
            raw = os.environ.get(f"TELEGRAM_THREAD_{(audience or 'fun').upper()}")
            thread = int(raw) if raw else None
        else:
            chat = os.environ.get("TELEGRAM_CHANNEL_ID")
        if not token or not chat:
            raise TelegramError("TELEGRAM_BOT_TOKEN / chat id not configured in .env")
        return cls(token, chat, thread)

    def _thread(self) -> dict:
        return {"message_thread_id": self.thread_id} if self.thread_id else {}

    def _call(self, method: str, **params) -> dict:
        for attempt in range(5):
            r = requests.post(f"{self.base}/{method}", json=params, timeout=30)
            data = r.json()
            if data.get("ok"):
                return data["result"]
            if r.status_code == 429:
                time.sleep(data.get("parameters", {}).get("retry_after", 5) + 1)
                continue
            if "message is not modified" in data.get("description", ""):
                return {}
            raise TelegramError(f"{method}: {data.get('description')}")
        raise TelegramError(f"{method}: rate limited too long")

    def send(self, text: str, silent: bool = False) -> int:
        res = self._call("sendMessage", chat_id=self.chat_id, text=text, parse_mode="HTML",
                         link_preview_options={"is_disabled": True}, disable_notification=silent, **self._thread())
        time.sleep(1.1)       # stay well below the per-chat flood limit
        return res["message_id"]

    def edit(self, message_id: int, text: str) -> None:
        self._call("editMessageText", chat_id=self.chat_id, message_id=message_id, text=text, parse_mode="HTML",
                   link_preview_options={"is_disabled": True})

    def delete(self, message_id: int) -> None:
        try:
            self._call("deleteMessage", chat_id=self.chat_id, message_id=message_id)
        except TelegramError as exc:
            log.warning("delete failed: %s", exc)

    def send_photo(self, photo_url: str, caption: str) -> int:
        res = self._call("sendPhoto", chat_id=self.chat_id, photo=photo_url, caption=caption[:1024], parse_mode="HTML", **self._thread())
        time.sleep(1.1)
        return res["message_id"]

    def pin(self, message_id: int) -> None:
        self._call("pinChatMessage", chat_id=self.chat_id, message_id=message_id, disable_notification=True)

"""Official Telegram Bot API client. Unsafe automatic retries of sendMessage are forbidden."""
from __future__ import annotations

from dataclasses import dataclass
import httpx


@dataclass
class TelegramError(Exception):
    message: str
    status: int | None = None
    retry_after: int | None = None
    uncertain: bool = False

    def __str__(self) -> str:
        return self.message


class TelegramClient:
    def __init__(self, token: str, *, transport=None):
        self.client = httpx.Client(
            base_url="https://api.telegram.org/bot" + token + "/",
            timeout=httpx.Timeout(15, connect=5),
            transport=transport,
            follow_redirects=False,
        )

    def close(self):
        self.client.close()

    def call(self, method: str, payload: dict):
        try:
            response = self.client.post(method, json=payload)
        except httpx.TransportError as exc:
            raise TelegramError("transport_unconfirmed", uncertain=True) from exc
        try:
            data = response.json()
        except (ValueError, TypeError) as exc:
            raise TelegramError("non_json_response", status=response.status_code, uncertain=True) from exc
        if not data.get("ok"):
            params = data.get("parameters") or {}
            raise TelegramError(
                str(data.get("description", "telegram_error"))[:150],
                status=int(data.get("error_code") or response.status_code),
                retry_after=params.get("retry_after"),
            )
        return data.get("result")

    def get_connection(self, connection_id: str):
        return self.call("getBusinessConnection", {"business_connection_id": connection_id})

    def answer_callback(self, callback_id: str):
        return self.call("answerCallbackQuery", {"callback_query_id": callback_id})

    def send(self, connection_id: str, chat_id: int, text: str, markup=None):
        data = {
            "business_connection_id": connection_id, "chat_id": chat_id,
            "text": text[:4000], "link_preview_options": {"is_disabled": True},
        }
        if markup:
            data["reply_markup"] = markup
        return self.call("sendMessage", data)

    def send_admin(self, chat_id: int, text: str):
        """Send from the bot (not the Business account) to an opt-in operator DM/group."""
        return self.call("sendMessage", {"chat_id": chat_id, "text": text[:4000],
                                         "link_preview_options": {"is_disabled": True}})

    def send_photo_admin(self, chat_id: int, file_id: str, caption: str):
        return self.call("sendPhoto", {"chat_id": chat_id, "photo": file_id,
                                       "caption": caption[:1024]})

    def edit(self, connection_id: str, chat_id: int, message_id: int, text: str, markup=None):
        data = {
            "business_connection_id": connection_id, "chat_id": chat_id,
            "message_id": message_id, "text": text[:4000],
            "link_preview_options": {"is_disabled": True},
        }
        if markup:
            data["reply_markup"] = markup
        return self.call("editMessageText", data)

    def set_webhook(self, url: str, secret: str, allowed_updates=None):
        return self.call("setWebhook", {
            "url": url, "secret_token": secret, "allowed_updates": allowed_updates or [
                "business_connection", "business_message", "edited_business_message",
                "deleted_business_messages", "callback_query",
            ],
            "drop_pending_updates": False,
        })

    def webhook_info(self):
        return self.call("getWebhookInfo", {})

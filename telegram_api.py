"""Minimal async wrapper around Telegram's HTTPS Bot API."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any


class TelegramBotAPIError(RuntimeError):
    """A Bot API error that never includes the token-bearing request URL."""


class TelegramBotAPI:
    def __init__(self, token: str):
        token = str(token or "").strip()
        if not token:
            raise RuntimeError("configure BOT_TOKEN in the local AskTg settings")
        self._base_url = f"https://api.telegram.org/bot{token}"

    def _call_sync(self, method: str, payload: dict[str, Any] | None, timeout: float) -> Any:
        request = urllib.request.Request(
            f"{self._base_url}/{method}",
            data=json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            try:
                details = json.loads(error.read().decode("utf-8"))
                description = str(details.get("description", ""))
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                description = ""
            message = description or f"HTTP {error.code}"
            raise TelegramBotAPIError(f"Telegram Bot API {method} failed: {message}") from None
        except urllib.error.URLError as error:
            reason = str(getattr(error, "reason", "network error"))
            raise TelegramBotAPIError(f"Telegram Bot API {method} connection failed: {reason}") from None
        except TimeoutError:
            raise TelegramBotAPIError(f"Telegram Bot API {method} timed out") from None
        except OSError as error:
            raise TelegramBotAPIError(f"Telegram Bot API {method} failed: {error}") from None

        try:
            response_data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TelegramBotAPIError(f"Telegram Bot API {method} returned invalid JSON") from None
        if not isinstance(response_data, dict):
            raise TelegramBotAPIError(f"Telegram Bot API {method} returned an invalid response")
        if not response_data.get("ok"):
            error_code = response_data.get("error_code", "")
            description = str(response_data.get("description", "request rejected"))
            prefix = f"HTTP {error_code}: " if error_code else ""
            raise TelegramBotAPIError(f"Telegram Bot API {method} failed: {prefix}{description}")
        return response_data.get("result")

    async def call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 20,
    ) -> Any:
        return await asyncio.to_thread(self._call_sync, method, payload, timeout)

    async def get_me(self) -> dict[str, Any]:
        result = await self.call("getMe")
        return result if isinstance(result, dict) else {}

    async def get_updates(
        self,
        offset: int,
        *,
        timeout: int = 25,
        allowed_updates: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        result = await self.call(
            "getUpdates",
            {
                "offset": int(offset),
                "timeout": int(timeout),
                "allowed_updates": allowed_updates or ["message"],
            },
            timeout=max(40, int(timeout) + 10),
        )
        return result if isinstance(result, list) else []

    async def send_message(self, chat_id: int | str, text: str) -> dict[str, Any]:
        text = str(text).strip()
        if not text or len(text) > 4096:
            raise ValueError("message must contain 1..4096 characters")
        result = await self.call("sendMessage", {"chat_id": chat_id, "text": text})
        return result if isinstance(result, dict) else {"ok": True}

    async def set_message_reaction(
        self,
        chat_id: int | str,
        message_id: int,
        emoji: str = "👀",
    ) -> bool:
        if int(message_id) <= 0:
            raise ValueError("message_id must be a positive integer")
        if not isinstance(emoji, str) or not emoji or len(emoji) > 8:
            raise ValueError("emoji must contain one Telegram reaction")
        result = await self.call(
            "setMessageReaction",
            {
                "chat_id": chat_id,
                "message_id": int(message_id),
                "reaction": [{"type": "emoji", "emoji": emoji}],
                "is_big": False,
            },
        )
        return bool(result)

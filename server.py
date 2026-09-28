from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from local_paths import CHATS_FILE, CREDENTIALS_DIR, ENV_FILE
from telegram_api import TelegramBotAPI, TelegramBotAPIError

mcp = FastMCP("AskTg")
AGENT_INSTRUCTIONS_FILE = Path(__file__).with_name("AgentInstructions.md")

try:
    from dotenv import load_dotenv

    load_dotenv(ENV_FILE)
except ImportError:
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
AGENT_GROUP_IDS: set[int] = set()
for _group_id in os.getenv("ASKTG_AGENT_GROUP_IDS", "").split(","):
    try:
        if _group_id.strip():
            AGENT_GROUP_IDS.add(int(_group_id.strip()))
    except ValueError as error:
        raise RuntimeError("ASKTG_AGENT_GROUP_IDS must contain comma-separated integer chat IDs") from error


def _load_chats() -> dict[str, dict[str, Any]]:
    if not CHATS_FILE.exists():
        return {}
    try:
        data = json.loads(CHATS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_chats(chats: dict[str, dict[str, Any]]) -> None:
    CREDENTIALS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = CHATS_FILE.with_suffix(CHATS_FILE.suffix + ".tmp")
    temporary.write_text(json.dumps(chats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, CHATS_FILE)


async def _get_client() -> TelegramBotAPI:
    token = os.getenv("BOT_TOKEN", BOT_TOKEN).strip()
    if not token:
        raise RuntimeError(f"configure BOT_TOKEN in the local AskTg settings: {ENV_FILE}")
    return TelegramBotAPI(token)


@mcp.tool()
async def sync_chats() -> dict:
    """Ensure the Bot API listener is running and return locally known chats."""
    try:
        from listener_watchdog import ensure_listener

        listener = await asyncio.to_thread(ensure_listener, timeout_seconds=8)
        return {"ok": True, "chats": _load_chats(), "listener": listener}
    except Exception as error:
        return {"ok": False, "error": str(error), "chats": _load_chats()}


@mcp.tool()
def list_known_chats() -> dict:
    """List users and allowed groups already observed by the local listener."""
    return {"ok": True, "chats": _load_chats()}


@mcp.tool()
def get_agent_instructions() -> str:
    """Return the portable collaboration rules for AskTg-connected agents."""
    try:
        return AGENT_INSTRUCTIONS_FILE.read_text(encoding="utf-8")
    except OSError as error:
        return "AskTg agent instructions are unavailable: " + str(error)


@mcp.tool()
def setup_status() -> dict:
    """Report configuration readiness without returning any credential values."""
    try:
        from dotenv import dotenv_values

        values = dotenv_values(ENV_FILE)
    except Exception:
        values = {}
    bot_token = values.get("BOT_TOKEN") or os.getenv("BOT_TOKEN", "")
    groups = values.get("ASKTG_AGENT_GROUP_IDS") or os.getenv("ASKTG_AGENT_GROUP_IDS", "")
    runner_enabled = values.get("ASKTG_AGENT_AUTO_RUN") or os.getenv("ASKTG_AGENT_AUTO_RUN", "0")
    return {
        "ok": True,
        "credentials_configured": bool(bot_token),
        "group_ids_configured": bool(str(groups).strip()),
        "runner_enabled": str(runner_enabled).strip() == "1",
        "credentials_file_exists": ENV_FILE.is_file(),
    }


@mcp.tool()
async def send_telegram_message(text: str, chat_id: str = None, username: str = None) -> dict:
    """Send a message to a numeric chat ID or a known username."""
    chats = _load_chats()
    target_chat_id: int | str | None = chat_id
    if isinstance(target_chat_id, str):
        normalized = target_chat_id.strip()
        if normalized.lstrip("-").isdigit():
            target_chat_id = int(normalized)
        else:
            return {"ok": False, "error": "chat_id must be a numeric Telegram chat ID"}

    if target_chat_id is None and username:
        peer_username = username.lstrip("@").casefold()
        for known_chat_id, info in chats.items():
            if str(info.get("username", "")).casefold() == peer_username:
                target_chat_id = int(known_chat_id)
                break
        if target_chat_id is None:
            target_chat_id = "@" + peer_username
    if target_chat_id is None:
        return {"ok": False, "error": "chat_id or username is required"}
    if not str(text).strip() or len(str(text)) > 4096:
        return {"ok": False, "error": "message must contain 1..4096 characters"}

    try:
        client = await _get_client()
        sent = await client.send_message(target_chat_id, text)
        return {"ok": True, "message_id": sent.get("message_id")}
    except (TelegramBotAPIError, RuntimeError, ValueError) as error:
        return {"ok": False, "error": str(error)}


async def react_to_telegram_message(
    message_id: int,
    chat_id: str = None,
    emoji: str = "👀",
) -> dict:
    """React to one message using the Bot API after the agent deliberately reads it."""
    try:
        normalized_message_id = int(message_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "message_id must be a positive integer"}
    if normalized_message_id <= 0:
        return {"ok": False, "error": "message_id must be a positive integer"}
    if not isinstance(emoji, str) or not emoji or len(emoji) > 8:
        return {"ok": False, "error": "emoji must contain one Telegram reaction"}
    if not chat_id or not str(chat_id).strip().lstrip("-").isdigit():
        return {"ok": False, "error": "chat_id must be a numeric Telegram chat ID"}

    try:
        client = await _get_client()
        await client.set_message_reaction(int(chat_id), normalized_message_id, emoji)
        return {"ok": True}
    except (TelegramBotAPIError, RuntimeError, ValueError) as error:
        return {"ok": False, "error": str(error)}


if __name__ == "__main__":
    mcp.run()

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from telegram_api import TelegramBotAPI, TelegramBotAPIError

from local_paths import (
    COMMAND_DIR,
    HEARTBEAT_FILE,
    INBOX_FILE,
    PID_FILE,
    STATE_DIR,
    TELEGRAM_UPDATE_OFFSET_FILE,
)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from server import AGENT_GROUP_IDS, BOT_TOKEN, _load_chats, _save_chats


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def append_inbox(value: dict) -> None:
    INBOX_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with INBOX_FILE.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_update_offset() -> int:
    try:
        value = json.loads(TELEGRAM_UPDATE_OFFSET_FILE.read_text(encoding="utf-8"))
        return max(0, int(value.get("next_offset", 0)))
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError, AttributeError):
        return 0


def last_inbox_update_offset() -> int:
    """Recover an update offset if the listener stopped after appending an inbox row."""
    try:
        with INBOX_FILE.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            end = stream.tell()
            if end == 0:
                return 0
            position = end - 1
            while position >= 0:
                stream.seek(position)
                if stream.read(1) not in {b"\n", b"\r"}:
                    break
                position -= 1
            while position >= 0:
                stream.seek(position)
                if stream.read(1) == b"\n":
                    position += 1
                    break
                position -= 1
            stream.seek(max(0, position))
            line = stream.readline().decode("utf-8")
        update_id = int(json.loads(line).get("update_id", 0))
        return update_id + 1 if update_id > 0 else 0
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, AttributeError):
        return 0


def write_update_offset(next_offset: int) -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    atomic_json(TELEGRAM_UPDATE_OFFSET_FILE, {"next_offset": int(next_offset)})


async def heartbeat() -> None:
    while True:
        atomic_json(
            HEARTBEAT_FILE,
            {"pid": os.getpid(), "updated_at": datetime.now(timezone.utc).isoformat()},
        )
        await asyncio.sleep(5)


async def command_worker(client: TelegramBotAPI) -> None:
    COMMAND_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    while True:
        for request_path in COMMAND_DIR.glob("*.request.json"):
            result_path = request_path.with_name(
                request_path.name.replace(".request.json", ".result.json")
            )
            try:
                request = json.loads(request_path.read_text(encoding="utf-8"))
                chat_id = int(str(request["chat_id"]).strip())
                action = str(request.get("action", ""))
                if action == "react":
                    await client.set_message_reaction(
                        chat_id,
                        int(request["message_id"]),
                        str(request.get("emoji", "\U0001F440")),
                    )
                elif action == "send":
                    await client.send_message(chat_id, str(request.get("text", "")))
                else:
                    raise ValueError("unsupported listener command")
                result = {"ok": True}
            except Exception as error:
                result = {"ok": False, "error": str(error)}

            # A hook requester removes a timed-out request. Do not leave a late
            # result that a later hook invocation could mistake for its own.
            if request_path.exists():
                atomic_json(result_path, result)
                if not request_path.exists():
                    result_path.unlink(missing_ok=True)
            request_path.unlink(missing_ok=True)
        await asyncio.sleep(0.05)


def message_text(message: dict) -> str:
    return str(message.get("text") or message.get("caption") or "")


def is_command(text: str, command: str, bot_username: str) -> bool:
    if not text:
        return False
    token = text.split(maxsplit=1)[0]
    base, separator, addressed_to = token.partition("@")
    if base.casefold() != command.casefold():
        return False
    return not separator or addressed_to.casefold() == bot_username.casefold()


async def handle_message(
    update_id: int,
    message: dict,
    client: TelegramBotAPI,
    bot_username: str,
) -> None:
    sender = message.get("from")
    chat = message.get("chat")
    if not isinstance(sender, dict) or not isinstance(chat, dict):
        return
    try:
        sender_id = int(sender["id"])
        chat_id = int(chat["id"])
    except (KeyError, TypeError, ValueError):
        return

    text = message_text(message)
    chat_type = str(chat.get("type", ""))
    chats = _load_chats()

    if chat_type == "private":
        sender_chat_id = str(sender_id)
        is_admin = bool(chats.get(sender_chat_id, {}).get("is_admin", False))
        if not any(bool(info.get("is_admin")) for info in chats.values() if isinstance(info, dict)):
            is_admin = True
        chats[sender_chat_id] = {
            "id": sender_chat_id,
            "type": "private",
            "username": str(sender.get("username", "") or ""),
            "first_name": str(sender.get("first_name", "") or ""),
            "is_admin": is_admin,
        }
        _save_chats(chats)
        if not is_admin:
            return
    elif chat_type in {"group", "supergroup"}:
        if chat_id not in AGENT_GROUP_IDS:
            known_sender = chats.get(str(sender_id), {})
            if is_command(text, "/asktg_group", bot_username) and known_sender.get("is_admin"):
                try:
                    await client.send_message(
                        chat_id,
                        "Эта группа пока не подключена. Добавьте локально в .env:\n"
                        f"ASKTG_AGENT_GROUP_IDS={chat_id}\n"
                        "Затем перезапустите listener.",
                    )
                except TelegramBotAPIError as error:
                    print(f"AskTg group discovery reply failed: {error}", file=sys.stderr, flush=True)
            return
        chats[str(chat_id)] = {
            "id": str(chat_id),
            "type": chat_type,
            "title": str(chat.get("title", "") or ""),
            "is_admin": False,
        }
        _save_chats(chats)
    else:
        return

    reply_to = message.get("reply_to_message")
    append_inbox(
        {
            "update_id": int(update_id),
            "message_id": int(message.get("message_id", 0) or 0),
            "chat_id": chat_id,
            "chat_title": str(chat.get("title") or chat.get("first_name") or ""),
            "sender_id": sender_id,
            "sender_username": str(sender.get("username", "") or ""),
            "sender_name": str(sender.get("first_name", "") or ""),
            "sender_is_bot": bool(sender.get("is_bot", False)),
            "reply_to_message_id": reply_to.get("message_id") if isinstance(reply_to, dict) else None,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "text": text,
        }
    )
    if chat_type == "private" and is_command(text, "/start", bot_username):
        try:
            await client.send_message(chat_id, "Привет. Канал AskTg активен.")
        except TelegramBotAPIError as error:
            print(f"AskTg start reply failed: {error}", file=sys.stderr, flush=True)


async def main() -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    INBOX_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    try:
        client = TelegramBotAPI(BOT_TOKEN)
        bot = await client.get_me()
        webhook = await client.call("getWebhookInfo")
        if isinstance(webhook, dict) and webhook.get("url"):
            raise RuntimeError(
                "this bot already has a webhook configured; AskTg polling cannot run alongside it"
            )
    except BaseException:
        PID_FILE.unlink(missing_ok=True)
        HEARTBEAT_FILE.unlink(missing_ok=True)
        raise

    bot_username = str(bot.get("username", "") or "")
    offset = max(read_update_offset(), last_inbox_update_offset())
    retry_delay = 1.0
    last_poll_error = ""
    heartbeat_task = asyncio.create_task(heartbeat())
    command_task = asyncio.create_task(command_worker(client))
    try:
        while True:
            try:
                updates = await client.get_updates(offset, timeout=25, allowed_updates=["message"])
            except TelegramBotAPIError as error:
                error_text = str(error)
                if error_text != last_poll_error:
                    print(f"AskTg Bot API polling unavailable: {error_text}", file=sys.stderr, flush=True)
                    last_poll_error = error_text
                await asyncio.sleep(retry_delay)
                retry_delay = min(30.0, retry_delay * 2)
                continue

            retry_delay = 1.0
            last_poll_error = ""

            for update in updates:
                try:
                    update_id = int(update.get("update_id", 0))
                    if update_id < offset:
                        continue
                    message = update.get("message")
                    if isinstance(message, dict):
                        await handle_message(update_id, message, client, bot_username)
                    offset = update_id + 1
                    write_update_offset(offset)
                except Exception as error:
                    # Keep the offset unchanged so a transient local write
                    # failure is retried rather than silently dropping input.
                    print(f"AskTg update processing failed: {error}", file=sys.stderr, flush=True)
                    await asyncio.sleep(2)
                    break
    finally:
        heartbeat_task.cancel()
        command_task.cancel()
        await asyncio.gather(heartbeat_task, command_task, return_exceptions=True)
        PID_FILE.unlink(missing_ok=True)
        HEARTBEAT_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())

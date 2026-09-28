import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import server
from local_paths import COMMAND_DIR, CURSOR_FILE, INBOX_FILE


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="strict")


# A reaction is an acknowledgement hint, not the delivery channel.  Keep a
# hook invocation bounded even when Telegram is reconnecting or flood-limited.
REACTION_TIMEOUT_SECONDS = 2.0


def admin_chat_id() -> str:
    chats = server._load_chats()
    for chat_id, info in chats.items():
        if info.get("is_admin"):
            return chat_id
    raise RuntimeError("no admin chat is registered")


async def send(text_file: Path) -> dict:
    text = text_file.read_text(encoding="utf-8").strip()
    if not text or len(text) > 4096:
        raise ValueError("message must contain 1..4096 characters")
    return await request_listener_send(text, chat_id=admin_chat_id())


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


async def _request_listener(command: dict, timeout_seconds: float = 8) -> dict:
    """Run Telegram I/O through the long-lived listener process."""
    COMMAND_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    request_id = uuid.uuid4().hex
    request_path = COMMAND_DIR / f"{request_id}.request.json"
    result_path = COMMAND_DIR / f"{request_id}.result.json"
    command = dict(command)
    command.update(
        {
            "request_id": request_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _atomic_json(
        request_path,
        command,
    )

    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                await asyncio.sleep(0.05)
                continue
            return result
        return {"ok": False, "error": "listener reaction timed out"}
    finally:
        request_path.unlink(missing_ok=True)
        result_path.unlink(missing_ok=True)


async def request_listener_reaction(
    message_id: int,
    chat_id: str,
    emoji: str = "\U0001F440",
    timeout_seconds: float = 8,
) -> dict:
    return await _request_listener(
        {
            "action": "react",
            "message_id": int(message_id),
            "chat_id": str(chat_id),
            "emoji": emoji,
        },
        timeout_seconds=timeout_seconds,
    )


async def request_listener_send(
    text: str,
    chat_id: str,
    timeout_seconds: float = 8,
) -> dict:
    return await _request_listener(
        {
            "action": "send",
            "chat_id": str(chat_id),
            "text": text,
        },
        timeout_seconds=timeout_seconds,
    )


async def inbox(after: int, limit: int, cursors: dict | None = None) -> list[dict]:
    if not INBOX_FILE.exists():
        return []
    messages = []
    for line in INBOX_FILE.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            message_id = int(item.get("message_id", 0))
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            continue
        if message_id <= 0:
            continue
        item["message_id"] = message_id
        item_chat_id = str(item.get("chat_id") or admin_chat_id())
        item["chat_id"] = item_chat_id
        if cursors is None:
            threshold = int(after)
        else:
            threshold = int(cursors.get(item_chat_id, 0))
            if item_chat_id == str(admin_chat_id()):
                threshold = int(cursors.get(item_chat_id, cursors.get("*", 0)))
        if message_id > threshold:
            messages.append(item)
    messages = messages[:limit]

    # The hook must not start a second getUpdates poller: Telegram permits one
    # active polling connection per bot. The listener owns I/O and acknowledges
    # before text reaches Codex.
    for item in messages:
        result = await request_listener_reaction(
            int(item.get("message_id", 0)),
            chat_id=str(item["chat_id"]),
            emoji="\U0001F440",
            timeout_seconds=REACTION_TIMEOUT_SECONDS,
        )
        item["acknowledgement"] = {
            "attempted": True,
            "ok": bool(result.get("ok")),
        }
        if not result.get("ok"):
            # A reaction is the first acknowledgement attempt, but Telegram
            # rejects reactions for some service/deleted messages.  Do not let
            # that optional UI action block delivery or cursor advancement.
            item["acknowledgement"]["error"] = str(
                result.get("error", "unknown error")
            )
    return messages


def read_cursor() -> int:
    cursors = read_cursors()
    return max(cursors.values(), default=0)


def read_cursors() -> dict[str, int]:
    try:
        value = json.loads(CURSOR_FILE.read_text(encoding="utf-8"))
        raw = value.get("last_message_ids", {})
        cursors = {
            str(chat_id): max(0, int(message_id))
            for chat_id, message_id in raw.items()
        } if isinstance(raw, dict) else {}
        legacy = max(0, int(value.get("last_message_id", 0)))
        if legacy:
            cursors.setdefault("*", legacy)
        return cursors
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def write_cursor(message_id: int, chat_id: str | int | None = None) -> None:
    CURSOR_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    cursors = read_cursors()
    cursor_key = str(chat_id) if chat_id is not None else "*"
    cursors[cursor_key] = max(cursors.get(cursor_key, 0), int(message_id))
    temporary = CURSOR_FILE.with_suffix(CURSOR_FILE.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "last_message_id": max(cursors.values(), default=0),
                "last_message_ids": cursors,
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, CURSOR_FILE)


async def checkpoint(limit: int) -> list[dict]:
    messages = await inbox(0, limit, cursors=read_cursors())
    if messages:
        last_by_chat: dict[str, int] = {}
        for item in messages:
            chat_id = str(item.get("chat_id") or admin_chat_id())
            last_by_chat[chat_id] = max(
                last_by_chat.get(chat_id, 0), int(item.get("message_id", 0))
            )
        for chat_id, message_id in last_by_chat.items():
            write_cursor(message_id, chat_id=chat_id)
    return messages


def latest_inbox_message_id() -> int:
    latest_by_chat = latest_inbox_message_ids()
    return max(latest_by_chat.values(), default=0)


def latest_inbox_message_ids() -> dict[str, int]:
    latest: dict[str, int] = {}
    if not INBOX_FILE.exists():
        return latest
    for line in INBOX_FILE.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            message_id = int(item.get("message_id", 0))
            chat_id = str(item.get("chat_id") or admin_chat_id())
            latest[chat_id] = max(latest.get(chat_id, 0), message_id)
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            continue
    return latest


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    send_parser = subparsers.add_parser("send")
    send_parser.add_argument("--text-file", type=Path, required=True)
    inbox_parser = subparsers.add_parser("inbox")
    inbox_parser.add_argument("--after", type=int, default=0)
    inbox_parser.add_argument("--limit", type=int, default=20)
    checkpoint_parser = subparsers.add_parser("checkpoint")
    checkpoint_parser.add_argument("--limit", type=int, default=100)
    subparsers.add_parser("cursor-to-latest")
    args = parser.parse_args()

    if args.command == "send":
        result = asyncio.run(send(args.text_file))
        print(json.dumps({"ok": bool(result.get("ok"))}, ensure_ascii=False))
        raise SystemExit(0 if result.get("ok") else 1)
    if args.command == "cursor-to-latest":
        latest = latest_inbox_message_ids()
        if latest:
            for chat_id, message_id in latest.items():
                write_cursor(message_id, chat_id=chat_id)
        else:
            write_cursor(0)
        print(json.dumps({"ok": True, "last_message_ids": latest}, ensure_ascii=False))
        return
    if args.limit < 1 or args.limit > 100:
        raise SystemExit("limit must be between 1 and 100")
    if args.command == "checkpoint":
        messages = asyncio.run(checkpoint(args.limit))
    else:
        messages = asyncio.run(inbox(args.after, args.limit))
    print(json.dumps({"ok": True, "messages": messages}, ensure_ascii=False))


if __name__ == "__main__":
    main()

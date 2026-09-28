import argparse
import asyncio
import json
import sys

import notify
from listener_watchdog import ensure_listener


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


STOP_CHECKPOINT_LIMIT = 10
LISTENER_START_TIMEOUT_SECONDS = 8
COMPLETION_SEND_TIMEOUT_SECONDS = 10
COMPLETION_SEND_ATTEMPTS = 2


def compact_messages(messages: list[dict]) -> str:
    lines = ["Новые сообщения из Telegram уже отмечены 👀. Учти их до продолжения:"]
    for item in messages:
        message_id = int(item.get("message_id", 0))
        text = str(item.get("text", "")).strip()
        sender = str(item.get("sender_name") or item.get("sender_username") or "Telegram")
        if item.get("sender_is_bot") and item.get("sender_username"):
            sender = "@" + str(item["sender_username"])
        sender_id = str(item.get("sender_id", ""))
        sender_tag = f" ({sender_id})" if sender_id else ""
        chat = str(item.get("chat_title") or "")
        location = f" [{chat}]" if chat else ""
        lines.append(f"TG{location} {sender}{sender_tag} #{message_id}: {text}")
    return "\n".join(lines)[:12000]


def parse_event(default_event: str, raw_input: str) -> tuple[str, dict]:
    """Return a normalized event name even when Codex sends an empty payload.

    The hook command is registered separately for Stop and non-stop events.
    Passing a default from that registration keeps the Stop notification alive
    across Codex versions that occasionally invoke a command without JSON on
    stdin.  A valid hook payload always wins over the default.
    """
    try:
        event = json.loads(raw_input) if raw_input.strip() else {}
    except json.JSONDecodeError:
        event = {}
    if not isinstance(event, dict):
        event = {}
    event_name = str(event.get("hook_event_name") or default_event).strip().casefold()
    event_name = event_name.replace("_", "").replace("-", "")
    return event_name, event


def send_completion_notice() -> str:
    last_error = "listener rejected send"
    for _attempt in range(COMPLETION_SEND_ATTEMPTS):
        try:
            result = asyncio.run(
                notify.request_listener_send(
                    "Кодекс завершил свой сеанс",
                    chat_id=notify.admin_chat_id(),
                    timeout_seconds=COMPLETION_SEND_TIMEOUT_SECONDS,
                )
            )
        except Exception as error:
            last_error = str(error)
            continue
        if result.get("ok"):
            return ""
        last_error = str(result.get("error", last_error))
    return "ASKTG completion notice failed: " + last_error


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--default-event",
        choices=("stop", "observe"),
        default="observe",
        help="fallback event when Codex provides no JSON payload",
    )
    # When executed as a hook script, argv=None must mean the real process
    # arguments.  Parsing an empty list here silently discarded the
    # registration's --default-event flag and made the Stop hook behave like
    # an observe hook again.
    args = parser.parse_args(argv)

    try:
        raw_input = sys.stdin.read()
    except (OSError, UnicodeError):
        raw_input = ""

    event_name, _event = parse_event(args.default_event, raw_input)
    is_stop = event_name == "stop"
    context_event = event_name in {"posttooluse", "sessionstart"}

    listener_warning = ""
    completion_warning = ""
    listener_ready = True
    try:
        ensure_listener(timeout_seconds=LISTENER_START_TIMEOUT_SECONDS)
    except Exception as error:
        listener_warning = f"ASKTG listener recovery failed: {error}"
        listener_ready = False

    try:
        if is_stop:
            messages = asyncio.run(notify.checkpoint(limit=STOP_CHECKPOINT_LIMIT))
            if not messages and listener_ready:
                completion_warning = send_completion_notice()
        elif context_event:
            messages = asyncio.run(notify.checkpoint(limit=1))
        else:
            # Non-stop hooks may surface Telegram replies early, but their
            # systemMessage is not guaranteed to enter the model context.
            # Keep the durable cursor untouched so Stop cannot miss a reply.
            messages = asyncio.run(notify.inbox(notify.read_cursor(), limit=10))
    except Exception as error:
        warning = f"ASKTG checkpoint failed: {error}"
        print(json.dumps({"systemMessage": warning}, ensure_ascii=False))
        return

    if messages:
        message_context = compact_messages(messages)
        if listener_warning:
            message_context += "\n" + listener_warning
        if is_stop:
            output = {"systemMessage": message_context}
            # Stop hooks use the continuation decision, not the generic
            # ``continue`` flag.  ``continue: false`` explicitly wins over
            # continuation decisions and would make Codex finish the turn
            # instead of feeding the Telegram message into a new model turn.
            output.update(
                {
                    "decision": "block",
                    "reason": "New Telegram messages must be considered before finishing",
                }
            )
        elif context_event:
            event_label = "SessionStart" if event_name == "sessionstart" else "PostToolUse"
            output = {
                "hookSpecificOutput": {
                    "hookEventName": event_label,
                    "additionalContext": message_context,
                }
            }
        else:
            output = {"systemMessage": message_context}
        print(json.dumps(output, ensure_ascii=False))
        return

    if listener_warning:
        completion_warning = "\n".join(
            item for item in (completion_warning, listener_warning) if item
        )

    if completion_warning:
        print(json.dumps({"systemMessage": completion_warning}, ensure_ascii=False))


if __name__ == "__main__":
    main()

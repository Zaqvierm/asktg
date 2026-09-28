import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import notify


class InboxReadReactionTests(unittest.TestCase):
    def test_send_uses_listener_command_queue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            text_file = Path(temp_dir) / "message.txt"
            text_file.write_text("status update", encoding="utf-8")
            sent = []

            async def send(text, chat_id=None):
                sent.append((text, chat_id))
                return {"ok": True}

            with (
                patch.object(notify, "admin_chat_id", return_value="123456"),
                patch.object(notify, "request_listener_send", send),
            ):
                result = asyncio.run(notify.send(text_file))

        self.assertEqual({"ok": True}, result)
        self.assertEqual([("status update", "123456")], sent)

    def test_inbox_reacts_before_returning_messages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            inbox_file = Path(temp_dir) / "inbox.jsonl"
            inbox_file.write_text(
                json.dumps({"message_id": 336, "text": "continue"}) + "\n",
                encoding="utf-8",
            )
            reacted = []

            async def react(message_id, chat_id=None, emoji="", timeout_seconds=0):
                reacted.append((message_id, chat_id, emoji))
                return {"ok": True}

            with (
                patch.object(notify, "INBOX_FILE", inbox_file),
                patch.object(notify, "admin_chat_id", return_value="123456"),
                patch.object(notify, "request_listener_reaction", react),
            ):
                messages = asyncio.run(notify.inbox(after=335, limit=20))

        self.assertEqual([(336, "123456", "👀")], reacted)
        self.assertEqual("continue", messages[0]["text"])

    def test_inbox_does_not_return_unacknowledged_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            inbox_file = Path(temp_dir) / "inbox.jsonl"
            inbox_file.write_text(
                json.dumps({"message_id": 336, "text": "stop"}) + "\n",
                encoding="utf-8",
            )

            async def reject(*_args, **_kwargs):
                return {"ok": False, "error": "reaction unavailable"}

            with (
                patch.object(notify, "INBOX_FILE", inbox_file),
                patch.object(notify, "admin_chat_id", return_value="123456"),
                patch.object(notify, "request_listener_reaction", reject),
            ):
                messages = asyncio.run(notify.inbox(after=335, limit=20))

        self.assertEqual(1, len(messages))
        self.assertFalse(messages[0]["acknowledgement"]["ok"])
        self.assertEqual("reaction unavailable", messages[0]["acknowledgement"]["error"])

    def test_inbox_skips_malformed_message_ids_without_failing_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            inbox_file = Path(temp_dir) / "inbox.jsonl"
            inbox_file.write_text(
                "\n".join(
                    [
                        json.dumps({"message_id": "not-a-number", "text": "bad"}),
                        json.dumps({"message_id": 0, "text": "zero"}),
                        json.dumps({"message_id": 336, "text": "valid"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            async def react(*_args, **_kwargs):
                return {"ok": True}

            with (
                patch.object(notify, "INBOX_FILE", inbox_file),
                patch.object(notify, "admin_chat_id", return_value="123456"),
                patch.object(notify, "request_listener_reaction", react),
            ):
                messages = asyncio.run(notify.inbox(after=335, limit=20))

        self.assertEqual([336], [item["message_id"] for item in messages])

    def test_checkpoint_persists_cursor_after_reaction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir)
            inbox_file = runtime / "inbox.jsonl"
            cursor_file = runtime / "cursor.json"
            inbox_file.write_text(
                "\n".join(
                    [
                        json.dumps({"message_id": 336, "text": "first"}),
                        json.dumps({"message_id": 337, "text": "second"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            async def react(*_args, **_kwargs):
                return {"ok": True}

            with (
                patch.object(notify, "INBOX_FILE", inbox_file),
                patch.object(notify, "CURSOR_FILE", cursor_file),
                patch.object(notify, "admin_chat_id", return_value="123456"),
                patch.object(notify, "request_listener_reaction", react),
            ):
                first = asyncio.run(notify.checkpoint(limit=20))
                second = asyncio.run(notify.checkpoint(limit=20))
                cursor_value = json.loads(cursor_file.read_text())["last_message_id"]

        self.assertEqual([336, 337], [item["message_id"] for item in first])
        self.assertEqual([], second)
        self.assertEqual(337, cursor_value)

    def test_checkpoint_does_not_advance_cursor_when_reaction_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir)
            inbox_file = runtime / "inbox.jsonl"
            cursor_file = runtime / "cursor.json"
            inbox_file.write_text(
                json.dumps({"message_id": 336, "text": "stop"}) + "\n",
                encoding="utf-8",
            )

            async def reject(*_args, **_kwargs):
                return {"ok": False, "error": "reaction unavailable"}

            with (
                patch.object(notify, "INBOX_FILE", inbox_file),
                patch.object(notify, "CURSOR_FILE", cursor_file),
                patch.object(notify, "admin_chat_id", return_value="123456"),
                patch.object(notify, "request_listener_reaction", reject),
            ):
                messages = asyncio.run(notify.checkpoint(limit=20))
                cursor_value = json.loads(cursor_file.read_text())["last_message_id"]

        self.assertEqual([336], [item["message_id"] for item in messages])
        self.assertEqual(336, cursor_value)


if __name__ == "__main__":
    unittest.main()

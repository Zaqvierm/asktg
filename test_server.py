import asyncio
import unittest
from unittest.mock import patch

import server


class FakeClient:
    def __init__(self):
        self.target = None
        self.text = None
        self.reaction = None

    async def send_message(self, target, text):
        self.target = target
        self.text = text
        return {"message_id": 41}

    async def set_message_reaction(self, target, message_id, emoji):
        self.target = target
        self.reaction = (message_id, emoji)
        return True


class SendTelegramMessageTests(unittest.TestCase):
    def test_numeric_chat_id_from_json_is_sent_as_integer(self):
        client = FakeClient()

        async def get_client():
            return client

        with patch.object(server, "_get_client", get_client):
            result = asyncio.run(server.send_telegram_message("status", chat_id="123456"))

        self.assertEqual({"ok": True, "message_id": 41}, result)
        self.assertEqual(123456, client.target)
        self.assertEqual("status", client.text)

    def test_non_numeric_chat_id_is_rejected_before_connect(self):
        result = asyncio.run(server.send_telegram_message("status", chat_id="not-an-id"))
        self.assertEqual({"ok": False, "error": "chat_id must be a numeric Telegram chat ID"}, result)

    def test_read_reaction_uses_numeric_chat_and_exact_message(self):
        client = FakeClient()

        async def get_client():
            return client

        with patch.object(server, "_get_client", get_client):
            result = asyncio.run(
                server.react_to_telegram_message(335, chat_id="123456", emoji="👀")
            )

        self.assertEqual({"ok": True}, result)
        self.assertEqual(123456, client.target)
        self.assertEqual((335, "👀"), client.reaction)

    def test_invalid_message_id_is_rejected_before_connect(self):
        result = asyncio.run(server.react_to_telegram_message(0, chat_id="123456", emoji="👀"))
        self.assertEqual(
            {"ok": False, "error": "message_id must be a positive integer"},
            result,
        )


if __name__ == "__main__":
    unittest.main()

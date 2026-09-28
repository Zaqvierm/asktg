import io
import json
import unittest
from unittest.mock import Mock, patch

import codex_hook


class CodexHookTests(unittest.TestCase):
    def run_hook(self, event: str, messages: list[dict]) -> tuple[dict, object, object]:
        stdin = io.StringIO(json.dumps({"hook_event_name": event}))
        stdout = io.StringIO()
        checkpoint = Mock(return_value=messages)
        inbox = Mock(return_value=messages)
        send = Mock(return_value={"ok": True})
        with (
            patch("sys.stdin", stdin),
            patch("sys.stdout", stdout),
            patch.object(codex_hook.notify, "checkpoint", new=checkpoint),
            patch.object(codex_hook.notify, "inbox", new=inbox),
            patch.object(codex_hook.notify, "request_listener_send", new=send),
            patch.object(codex_hook.notify, "admin_chat_id", return_value="123"),
            patch.object(codex_hook.notify, "read_cursor", return_value=349),
            patch.object(codex_hook.asyncio, "run", side_effect=lambda value: value),
            patch.object(codex_hook, "ensure_listener", return_value={"ok": True}),
        ):
            codex_hook.main([])
        output = json.loads(stdout.getvalue()) if stdout.getvalue() else {}
        return output, checkpoint, inbox

    def run_empty_payload_hook(
        self, default_event: str, messages: list[dict]
    ) -> tuple[dict, object, object, object]:
        stdin = io.StringIO("")
        stdout = io.StringIO()
        checkpoint = Mock(return_value=messages)
        inbox = Mock(return_value=messages)
        send = Mock(return_value={"ok": True})
        with (
            patch("sys.stdin", stdin),
            patch("sys.stdout", stdout),
            patch.object(codex_hook.notify, "checkpoint", new=checkpoint),
            patch.object(codex_hook.notify, "inbox", new=inbox),
            patch.object(codex_hook.notify, "request_listener_send", new=send),
            patch.object(codex_hook.notify, "admin_chat_id", return_value="123"),
            patch.object(codex_hook.notify, "read_cursor", return_value=349),
            patch.object(codex_hook.asyncio, "run", side_effect=lambda value: value),
            patch.object(codex_hook, "ensure_listener", return_value={"ok": True}),
        ):
            codex_hook.main(["--default-event", default_event])
        output = json.loads(stdout.getvalue()) if stdout.getvalue() else {}
        return output, checkpoint, inbox, send

    def test_post_tool_use_surfaces_message_without_stopping(self):
        output, checkpoint, inbox = self.run_hook(
            "PostToolUse", [{"message_id": 350, "text": "continue"}]
        )
        self.assertIn("TG #350: continue", output["systemMessage"])
        self.assertNotIn("continue", output)
        checkpoint.assert_not_called()
        inbox.assert_called_once_with(349, limit=10)

    def test_user_prompt_submit_does_not_advance_cursor(self):
        output, checkpoint, inbox = self.run_hook(
            "UserPromptSubmit", [{"message_id": 350, "text": "continue"}]
        )
        self.assertIn("TG #350: continue", output["systemMessage"])
        checkpoint.assert_not_called()
        inbox.assert_called_once_with(349, limit=10)

    def test_stop_hook_blocks_finish_when_message_arrived(self):
        output, checkpoint, inbox = self.run_hook(
            "Stop", [{"message_id": 351, "text": "I answered"}]
        )
        self.assertEqual("block", output["decision"])
        self.assertNotIn("continue", output)
        self.assertNotIn("stopReason", output)
        self.assertIn("considered before finishing", output["reason"])
        self.assertIn("TG #351: I answered", output["systemMessage"])
        checkpoint.assert_called_once_with(limit=10)
        inbox.assert_not_called()

    def test_stop_hook_notifies_after_clean_checkpoint(self):
        output, checkpoint, inbox = self.run_hook("Stop", [])
        self.assertEqual(output, {})
        checkpoint.assert_called_once_with(limit=10)
        inbox.assert_not_called()

    def test_empty_stop_payload_still_sends_completion_notice(self):
        output, checkpoint, inbox, send = self.run_empty_payload_hook("stop", [])
        self.assertEqual({}, output)
        checkpoint.assert_called_once_with(limit=10)
        inbox.assert_not_called()
        send.assert_called_once()

    def test_empty_non_stop_payload_does_not_send_completion_notice(self):
        output, checkpoint, inbox, send = self.run_empty_payload_hook("observe", [])
        self.assertEqual({}, output)
        checkpoint.assert_not_called()
        inbox.assert_called_once_with(349, limit=10)
        send.assert_not_called()

    def test_script_cli_arguments_select_stop_for_empty_payload(self):
        stdin = io.StringIO("")
        stdout = io.StringIO()
        checkpoint = Mock(return_value=[])
        send = Mock(return_value={"ok": True})
        with (
            patch("sys.stdin", stdin),
            patch("sys.stdout", stdout),
            patch("sys.argv", ["codex_hook.py", "--default-event", "stop"]),
            patch.object(codex_hook.notify, "checkpoint", new=checkpoint),
            patch.object(codex_hook.notify, "inbox", new=Mock()),
            patch.object(codex_hook.notify, "request_listener_send", new=send),
            patch.object(codex_hook.notify, "admin_chat_id", return_value="123"),
            patch.object(codex_hook.asyncio, "run", side_effect=lambda value: value),
            patch.object(codex_hook, "ensure_listener", return_value={"ok": True}),
        ):
            codex_hook.main()
        self.assertEqual({}, json.loads(stdout.getvalue()) if stdout.getvalue() else {})
        checkpoint.assert_called_once_with(limit=10)
        send.assert_called_once()

    def test_stop_hook_surfaces_send_failure_without_blocking_finish(self):
        stdin = io.StringIO(json.dumps({"hook_event_name": "Stop"}))
        stdout = io.StringIO()
        checkpoint = Mock(return_value=[])
        send = Mock(return_value={"ok": False, "error": "listener offline"})
        with (
            patch("sys.stdin", stdin),
            patch("sys.stdout", stdout),
            patch.object(codex_hook.notify, "checkpoint", new=checkpoint),
            patch.object(codex_hook.notify, "request_listener_send", new=send),
            patch.object(codex_hook.notify, "admin_chat_id", return_value="123"),
            patch.object(codex_hook.asyncio, "run", side_effect=lambda value: value),
            patch.object(codex_hook, "ensure_listener", return_value={"ok": True}),
        ):
            codex_hook.main([])
        output = json.loads(stdout.getvalue())
        self.assertIn("completion notice failed", output["systemMessage"])

    def test_stop_hook_does_not_wait_for_send_when_listener_recovery_fails(self):
        stdin = io.StringIO(json.dumps({"hook_event_name": "Stop"}))
        stdout = io.StringIO()
        checkpoint = Mock(return_value=[])
        send = Mock(return_value={"ok": True})
        with (
            patch("sys.stdin", stdin),
            patch("sys.stdout", stdout),
            patch.object(codex_hook.notify, "checkpoint", new=checkpoint),
            patch.object(codex_hook.notify, "request_listener_send", new=send),
            patch.object(codex_hook.notify, "admin_chat_id", return_value="123"),
            patch.object(codex_hook.asyncio, "run", side_effect=lambda value: value),
            patch.object(
                codex_hook,
                "ensure_listener",
                side_effect=TimeoutError("listener unavailable"),
            ),
        ):
            codex_hook.main([])
        output = json.loads(stdout.getvalue())
        self.assertIn("listener recovery failed", output["systemMessage"])
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()

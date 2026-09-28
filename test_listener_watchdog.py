import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import listener_watchdog


class ListenerWatchdogTests(unittest.TestCase):
    def test_fresh_heartbeat_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            heartbeat = Path(temp_dir) / "heartbeat.json"
            pid_file = Path(temp_dir) / "daemon.pid"
            heartbeat.write_text(
                json.dumps({"updated_at": datetime.now(timezone.utc).isoformat()}),
                encoding="utf-8",
            )
            pid_file.write_text("1234", encoding="ascii")
            with (
                patch.object(listener_watchdog, "HEARTBEAT_FILE", heartbeat),
                patch.object(listener_watchdog, "PID_FILE", pid_file),
                patch.object(listener_watchdog, "pid_is_alive", return_value=True),
            ):
                self.assertTrue(listener_watchdog.receiver_is_fresh())

    def test_recent_heartbeat_from_dead_listener_is_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            heartbeat = Path(temp_dir) / "heartbeat.json"
            pid_file = Path(temp_dir) / "daemon.pid"
            heartbeat.write_text(
                json.dumps({"updated_at": datetime.now(timezone.utc).isoformat()}),
                encoding="utf-8",
            )
            pid_file.write_text("1234", encoding="ascii")
            with (
                patch.object(listener_watchdog, "HEARTBEAT_FILE", heartbeat),
                patch.object(listener_watchdog, "PID_FILE", pid_file),
                patch.object(listener_watchdog, "pid_is_alive", return_value=False),
            ):
                self.assertFalse(listener_watchdog.receiver_is_fresh())

    def test_ensure_does_not_spawn_when_listener_is_fresh(self):
        with (
            patch.object(listener_watchdog, "receiver_is_fresh", return_value=True),
            patch.object(listener_watchdog, "read_pid", return_value=1234),
            patch.object(listener_watchdog, "start_listener") as start,
        ):
            result = listener_watchdog.ensure_listener()
        self.assertEqual({"ok": True, "started": False, "pid": 1234}, result)
        start.assert_not_called()

    def test_posix_system_error_marks_stale_pid_dead(self):
        with (
            patch.object(listener_watchdog.os, "name", "posix"),
            patch.object(listener_watchdog.os, "kill", side_effect=SystemError("invalid handle")),
        ):
            self.assertFalse(listener_watchdog.pid_is_alive(2852))

    def test_windows_current_process_is_alive(self):
        with patch.object(listener_watchdog.os, "name", "nt"):
            self.assertTrue(listener_watchdog.pid_is_alive(os.getpid()))

    def test_stale_listener_is_replaced_and_heartbeat_is_required(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = Path(temp_dir)
            pid_file = state / "daemon.pid"
            heartbeat_file = state / "heartbeat.json"
            lock_file = state / "listener-start.lock"
            freshness = iter([False, False, True])
            with (
                patch.object(listener_watchdog, "STATE_DIR", state),
                patch.object(listener_watchdog, "PID_FILE", pid_file),
                patch.object(listener_watchdog, "HEARTBEAT_FILE", heartbeat_file),
                patch.object(listener_watchdog, "LOCK_FILE", lock_file),
                patch.object(listener_watchdog, "receiver_is_fresh", side_effect=lambda: next(freshness)),
                patch.object(listener_watchdog, "read_pid", return_value=4321),
                patch.object(listener_watchdog, "stop_stale_listener") as stop,
                patch.object(listener_watchdog, "start_listener", return_value=8765) as start,
                patch.object(listener_watchdog.time, "sleep"),
            ):
                result = listener_watchdog.ensure_listener(timeout_seconds=1)
        self.assertEqual({"ok": True, "started": True, "pid": 4321}, result)
        stop.assert_called_once_with(4321)
        start.assert_called_once_with()

    def test_start_timeout_kills_launcher_and_clears_markers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = Path(temp_dir)
            pid_file = state / "daemon.pid"
            heartbeat_file = state / "heartbeat.json"
            lock_file = state / "listener-start.lock"
            with (
                patch.object(listener_watchdog, "STATE_DIR", state),
                patch.object(listener_watchdog, "PID_FILE", pid_file),
                patch.object(listener_watchdog, "HEARTBEAT_FILE", heartbeat_file),
                patch.object(listener_watchdog, "LOCK_FILE", lock_file),
                patch.object(listener_watchdog, "receiver_is_fresh", return_value=False),
                patch.object(listener_watchdog, "read_pid", return_value=0),
                patch.object(listener_watchdog, "start_listener", return_value=8765),
                patch.object(listener_watchdog, "stop_stale_listener") as stop,
                patch.object(listener_watchdog.time, "sleep"),
            ):
                with self.assertRaises(TimeoutError):
                    listener_watchdog.ensure_listener(timeout_seconds=0)
        self.assertEqual([((0,), {}), ((8765,), {})], stop.call_args_list)
        self.assertFalse(pid_file.exists())
        self.assertFalse(heartbeat_file.exists())


if __name__ == "__main__":
    unittest.main()

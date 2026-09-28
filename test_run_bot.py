import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_bot


class CommandWorkerTests(unittest.TestCase):
    def test_request_removed_during_result_write_does_not_leave_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            command_dir = Path(temp_dir)
            request_path = command_dir / "request.request.json"
            result_path = command_dir / "request.result.json"
            request_path.write_text(
                json.dumps({"chat_id": "123", "action": "unknown"}),
                encoding="utf-8",
            )

            original_sleep = asyncio.sleep
            sleep_calls = 0

            async def controlled_sleep(_delay):
                nonlocal sleep_calls
                sleep_calls += 1
                if sleep_calls > 1:
                    raise asyncio.CancelledError
                await original_sleep(0)

            def write_then_remove(path, value):
                path.write_text(json.dumps(value), encoding="utf-8")
                request_path.unlink(missing_ok=True)

            async def exercise():
                task = asyncio.create_task(run_bot.command_worker(object()))
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            with (
                patch.object(run_bot, "COMMAND_DIR", command_dir),
                patch.object(run_bot, "atomic_json", side_effect=write_then_remove),
                patch.object(run_bot.asyncio, "sleep", controlled_sleep),
            ):
                asyncio.run(exercise())

            self.assertFalse(result_path.exists())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from runtime import runtime_python


def main() -> int:
    hook_input = sys.stdin.buffer.read()
    try:
        python = runtime_python()
        if not python.is_file():
            raise RuntimeError("AskTg's private runtime is not installed yet")
        result = subprocess.run(
            [str(python), str(PLUGIN_ROOT / "codex_hook.py"), *sys.argv[1:]],
            cwd=str(PLUGIN_ROOT),
            input=hook_input,
            stdout=sys.stdout.buffer,
            stderr=sys.stderr.buffer,
            check=False,
        )
        return result.returncode
    except Exception as error:
        try:
            event = json.loads(hook_input.decode("utf-8")) if hook_input else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            event = {}
        if not isinstance(event, dict):
            event = {}
        event_name = str(event.get("hook_event_name", "")).replace("_", "").replace("-", "").casefold()
        if event_name == "posttooluse":
            return 0
        if event_name == "stop" or "stop" in sys.argv:
            print(
                json.dumps({"systemMessage": f"AskTg hook is not ready: {error}"}, ensure_ascii=False),
                flush=True,
            )
        else:
            hook_label = "SessionStart" if event_name == "sessionstart" else "PostToolUse"
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": hook_label,
                            "additionalContext": f"AskTg hook is not ready. Run scripts/setup.py locally, then start a new Codex thread. Details: {error}",
                        }
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

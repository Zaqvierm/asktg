from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from runtime import ensure_runtime


def main() -> int:
    try:
        python = ensure_runtime(PLUGIN_ROOT)
        return subprocess.call(
            [str(python), str(PLUGIN_ROOT / "agent_runner.py")],
            cwd=str(PLUGIN_ROOT),
        )
    except Exception as error:
        print(f"AskTg runner could not start: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

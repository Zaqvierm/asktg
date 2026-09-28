"""Create the per-user Python runtime used by AskTg's local MCP server."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path

from local_paths import DATA_HOME


def runtime_python() -> Path:
    runtime = DATA_HOME / "runtime"
    if os.name == "nt":
        return runtime / "Scripts" / "python.exe"
    return runtime / "bin" / "python"


def ensure_runtime(plugin_root: Path) -> Path:
    if sys.version_info < (3, 11):
        raise RuntimeError("AskTg requires Python 3.11 or newer")

    requirements = plugin_root / "requirements.txt"
    if not requirements.is_file():
        raise RuntimeError("AskTg requirements.txt is missing from the plugin")
    requirement_hash = hashlib.sha256(requirements.read_bytes()).hexdigest()
    runtime = DATA_HOME / "runtime"
    python = runtime_python()
    marker = runtime / "requirements.sha256"
    try:
        installed_hash = marker.read_text(encoding="ascii").strip()
    except OSError:
        installed_hash = ""

    if not python.is_file():
        runtime.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True, clear=False).create(runtime)
        python = runtime_python()

    if installed_hash != requirement_hash:
        result = subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements)],
            cwd=str(plugin_root),
            stdin=subprocess.DEVNULL,
            stdout=sys.stderr,
            stderr=sys.stderr,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(f"dependency installation failed with exit code {result.returncode}")
        marker.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        marker.write_text(requirement_hash + "\n", encoding="ascii")
    return python

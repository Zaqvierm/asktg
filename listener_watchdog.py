import json
import ctypes
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from local_paths import HEARTBEAT_FILE, PID_FILE, STATE_DIR


ROOT = Path(__file__).parent
RUN_BOT = ROOT / "run_bot.py"
LOCK_FILE = STATE_DIR / "listener-start.lock"
LOG_FILE = STATE_DIR / "listener.log"


def receiver_is_fresh(max_age_seconds: int = 20) -> bool:
    try:
        heartbeat = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
        updated_at = datetime.fromisoformat(str(heartbeat["updated_at"]))
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
        return False
    if datetime.now(timezone.utc) - updated_at > timedelta(seconds=max_age_seconds):
        return False
    # A recent heartbeat is only useful while the process that emitted it is
    # still alive.  Without this check a crashed listener can leave a fresh
    # marker behind and every hook invocation will incorrectly skip recovery.
    return pid_is_alive(read_pid())


def read_pid() -> int:
    try:
        return int(PID_FILE.read_text(encoding="ascii").strip())
    except (FileNotFoundError, ValueError):
        return 0


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) is not a reliable existence check on Windows:
        # CPython can raise SystemError for a perfectly live process. Query
        # the process handle instead and distinguish STILL_ACTIVE from an
        # exited process.
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            process_query_limited_information = 0x1000
            still_active = 259
            handle = kernel32.OpenProcess(
                process_query_limited_information,
                False,
                pid,
            )
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            try:
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, TypeError, ValueError):
            return False
    try:
        os.kill(pid, 0)
    except (OSError, SystemError):
        return False
    return True


def stop_stale_listener(pid: int) -> None:
    if not pid_is_alive(pid):
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        os.kill(pid, 15)


def start_listener() -> int:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    log = LOG_FILE.open("ab", buffering=0)
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
    try:
        process = subprocess.Popen(
            [sys.executable, str(RUN_BOT)],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            close_fds=True,
            creationflags=creationflags,
        )
    finally:
        log.close()
    return int(process.pid)


def acquire_start_lock(timeout_seconds: float) -> int:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            return os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                if time.time() - LOCK_FILE.stat().st_mtime > 30:
                    LOCK_FILE.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if receiver_is_fresh():
                return -1
            if time.monotonic() >= deadline:
                raise TimeoutError("ASKTG listener start lock did not clear")
            time.sleep(0.2)


def ensure_listener(timeout_seconds: float = 12) -> dict:
    if receiver_is_fresh():
        return {"ok": True, "started": False, "pid": read_pid()}

    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_fd = acquire_start_lock(timeout_seconds)
    if lock_fd == -1:
        return {"ok": True, "started": False, "pid": read_pid()}

    launcher_pid = 0
    try:
        if receiver_is_fresh():
            return {"ok": True, "started": False, "pid": read_pid()}
        stale_pid = read_pid()
        stop_stale_listener(stale_pid)
        PID_FILE.unlink(missing_ok=True)
        HEARTBEAT_FILE.unlink(missing_ok=True)
        launcher_pid = start_listener()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if receiver_is_fresh():
                return {"ok": True, "started": True, "pid": read_pid() or launcher_pid}
            time.sleep(0.2)
        raise TimeoutError(f"ASKTG listener did not produce a heartbeat; launcher pid={launcher_pid}")
    except Exception:
        # Do not leave a detached Bot API listener behind when startup never
        # produced a heartbeat. Otherwise each hook timeout can accumulate a
        # new reconnecting listener and flood Telegram with duplicate traffic.
        if launcher_pid:
            stop_stale_listener(launcher_pid)
        PID_FILE.unlink(missing_ok=True)
        HEARTBEAT_FILE.unlink(missing_ok=True)
        raise
    finally:
        os.close(lock_fd)
        LOCK_FILE.unlink(missing_ok=True)


def main() -> None:
    try:
        result = ensure_listener()
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

import os
import sys
from pathlib import Path


def _default_home() -> Path:
    configured = os.getenv("ASKTG_HOME")
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "win32":
        roaming = os.getenv("APPDATA")
        if roaming:
            return Path(roaming) / "AskTg"
    data_home = os.getenv("XDG_DATA_HOME")
    if data_home:
        return Path(data_home).expanduser() / "asktg"
    return Path.home() / ".local" / "share" / "asktg"


DATA_HOME = _default_home()
AUTOMATION_DIR = Path(os.getenv("ASKTG_AUTOMATION_DIR", DATA_HOME / "automation"))
CREDENTIALS_DIR = Path(os.getenv("ASKTG_CREDENTIALS_DIR", DATA_HOME / "credentials"))
STATE_DIR = Path(os.getenv("ASKTG_STATE_DIR", DATA_HOME / "state"))
MESSAGES_DIR = Path(os.getenv("ASKTG_MESSAGES_DIR", DATA_HOME / "messages"))

ENV_FILE = Path(os.getenv("ASKTG_ENV_FILE", CREDENTIALS_DIR / ".env"))
CHATS_FILE = CREDENTIALS_DIR / "chats.json"
INBOX_FILE = MESSAGES_DIR / "asktg-inbox.jsonl"
CURSOR_FILE = STATE_DIR / "asktg-cursor.json"
TELEGRAM_UPDATE_OFFSET_FILE = STATE_DIR / "telegram-update-offset.json"
PID_FILE = STATE_DIR / "daemon.pid"
HEARTBEAT_FILE = STATE_DIR / "heartbeat.json"
COMMAND_DIR = STATE_DIR / "commands"

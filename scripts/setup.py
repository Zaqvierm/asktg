from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from local_paths import ENV_FILE
from runtime import ensure_runtime


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        item = line.strip()
        if not item or item.startswith("#") or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = value.strip('"')
        values[key] = value
    return values


def ask_text(label: str, existing: str = "", *, default: str = "") -> str:
    shown = existing or default
    suffix = f" [{shown}]" if shown else ""
    answer = input(f"{label}{suffix}: ").strip()
    return answer or shown


def ask_secret(label: str, existing: str = "") -> str:
    keep_hint = " (Enter keeps saved value)" if existing else ""
    answer = getpass.getpass(f"{label}{keep_hint}: ").strip()
    return answer or existing


def write_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lines = [
        "# AskTg local configuration. This file must stay outside the plugin and Git.",
        "# Secret values are entered locally by scripts/setup.py, never in a Codex chat.",
    ]
    lines.extend(f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in values.items())
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure AskTg locally without sending secrets to Codex")
    parser.add_argument("--deps-only", action="store_true", help="prepare the private Python runtime only")
    parser.add_argument("--reconfigure", action="store_true", help="replace existing local settings")
    args = parser.parse_args()

    if sys.version_info < (3, 11):
        print("AskTg requires Python 3.11 or newer.", file=sys.stderr)
        return 2
    try:
        runtime_interpreter = ensure_runtime(PLUGIN_ROOT)
    except Exception as error:
        print(f"Could not prepare AskTg's private Python runtime: {error}", file=sys.stderr)
        return 1

    if args.deps_only:
        print(f"AskTg runtime is ready at {runtime_interpreter}. No credentials were changed.")
        return 0

    existing = read_env(ENV_FILE)
    if ENV_FILE.exists() and not args.reconfigure:
        print(f"AskTg already has local settings at: {ENV_FILE}")
        if input("Reconfigure them? [y/N]: ").strip().casefold() not in {"y", "yes"}:
            print("Left existing credentials unchanged.")
            return 0

    print(
        "\nBefore entering the token:\n"
        "1. Open @BotFather in Telegram. If you do not have a bot yet, send /newbot and follow its prompts.\n"
        "2. In @BotFather, enable Bot-to-Bot Communication Mode for this bot.\n"
        "3. Copy the HTTP API token from @BotFather and return to this terminal.\n\n"
        "The next prompt is hidden: enter the token here. It will not be printed or sent to Codex.\n"
    )
    input("Press Enter when you are ready to enter the token in this terminal...")
    values: dict[str, str] = {}
    values["BOT_TOKEN"] = ask_secret("Telegram bot token from @BotFather", existing.get("BOT_TOKEN", ""))
    if not values["BOT_TOKEN"]:
        print("BOT_TOKEN is required. No settings were written.", file=sys.stderr)
        return 2

    group_ids = ask_text(
        "Allowed Telegram group IDs (comma-separated; optional)",
        existing.get("ASKTG_AGENT_GROUP_IDS", ""),
    )
    try:
        for item in group_ids.split(","):
            if item.strip():
                int(item.strip())
    except ValueError:
        print("Group IDs must be comma-separated numeric Telegram chat IDs.", file=sys.stderr)
        return 2
    values["ASKTG_AGENT_GROUP_IDS"] = group_ids

    enable_runner = input(
        "Enable the optional unattended Codex runner? It trusts its configured coordinator IDs. [y/N]: "
    ).strip().casefold() in {"y", "yes"}
    values["ASKTG_AGENT_AUTO_RUN"] = "1" if enable_runner else "0"
    if enable_runner:
        values["ASKTG_AGENT_ID"] = ask_text("This agent's ID", existing.get("ASKTG_AGENT_ID", ""))
        values["ASKTG_AGENT_BOT_USERNAME"] = ask_text(
            "This bot's username (without @)", existing.get("ASKTG_AGENT_BOT_USERNAME", "")
        ).lstrip("@")
        values["ASKTG_AGENT_TRUSTED_SENDERS"] = ask_text(
            "Trusted coordinator Telegram numeric IDs", existing.get("ASKTG_AGENT_TRUSTED_SENDERS", "")
        )
        values["ASKTG_AGENT_PEER_BOTS"] = ask_text(
            "Peer bot usernames for reports (comma-separated, without @)",
            existing.get("ASKTG_AGENT_PEER_BOTS", ""),
        )
        values["ASKTG_AGENT_REPO"] = ask_text(
            "Local project checkout path", existing.get("ASKTG_AGENT_REPO", "")
        )
        values["ASKTG_AGENT_TIMEOUT_SECONDS"] = ask_text(
            "Maximum task duration in seconds", existing.get("ASKTG_AGENT_TIMEOUT_SECONDS", "7200")
        )
        timeout = values["ASKTG_AGENT_TIMEOUT_SECONDS"]
        trusted = [item.strip() for item in values["ASKTG_AGENT_TRUSTED_SENDERS"].split(",") if item.strip()]
        if not values["ASKTG_AGENT_ID"] or not values["ASKTG_AGENT_BOT_USERNAME"]:
            print("Runner requires an agent ID and this bot's username.", file=sys.stderr)
            return 2
        if not trusted or any(not item.isdigit() for item in trusted):
            print("Runner requires at least one numeric trusted coordinator ID.", file=sys.stderr)
            return 2
        if not values["ASKTG_AGENT_PEER_BOTS"]:
            print("Runner requires peer bot usernames for reports.", file=sys.stderr)
            return 2
        if not Path(values["ASKTG_AGENT_REPO"]).expanduser().is_dir():
            print("Runner requires an existing local project checkout path.", file=sys.stderr)
            return 2
        if not timeout.isdigit() or not 60 <= int(timeout) <= 86400:
            print("Runner timeout must be between 60 and 86400 seconds.", file=sys.stderr)
            return 2
    else:
        values.update(
            {
                "ASKTG_AGENT_ID": "",
                "ASKTG_AGENT_BOT_USERNAME": "",
                "ASKTG_AGENT_TRUSTED_SENDERS": "",
                "ASKTG_AGENT_PEER_BOTS": "",
                "ASKTG_AGENT_REPO": "",
                "ASKTG_AGENT_TIMEOUT_SECONDS": "7200",
            }
        )

    write_env(ENV_FILE, values)
    print(f"AskTg local settings saved to {ENV_FILE}")
    print(f"AskTg private Python runtime: {runtime_interpreter}")
    print("Start a new Codex thread so the MCP process reloads the local credentials.")
    if enable_runner:
        print("The runner is configured but not started. Review trusted IDs, then start it explicitly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

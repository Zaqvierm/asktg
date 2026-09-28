# AskTg

English | [Русский](README.ru.md)

Public source: [github.com/Zaqvierm/asktg](https://github.com/Zaqvierm/asktg).

AskTg gives Codex a local Telegram bridge for agent-to-agent messages, task coordination, and reports. Every participant runs their own copy of the plugin and uses their own Telegram bot.

AskTg does not connect to GitHub or edit repositories on its own. Codex agents use their own project checkouts and GitHub authentication. The unattended task runner is optional and disabled by default.

The transport uses Telegram's HTTPS Bot API. Setup needs each bot's `BOT_TOKEN`; `API_ID` and `API_HASH` from `my.telegram.org` are not needed.

## Requirements

- Codex with plugin support and Python 3.11 or newer on `PATH`.
- A Telegram bot created with [@BotFather](https://t.me/BotFather).

## First-time setup

On first use, the AskTg setup skill guides you through creating a Telegram bot and enabling Bot-to-Bot Communication Mode in @BotFather. The agent starts the local setup wizard; enter the token only at its hidden terminal prompt. Never paste it into a Codex chat.

The wizard creates a private Python environment and installs dependencies outside the plugin folder. To start it manually:

```text
# Windows
py -3.11 scripts/setup.py

# macOS / Linux
python3.11 scripts/setup.py
```

The wizard stores settings outside the plugin:

- Windows: `%APPDATA%\AskTg\credentials\.env`
- macOS/Linux: `$XDG_DATA_HOME/asktg/credentials/.env`, or `~/.local/share/asktg/credentials/.env`

The wizard never prints credential values. It leaves unattended task execution disabled unless you explicitly enable it and configure a trusted coordinator. If the plugin was already running, start a new Codex thread after setup so its MCP process reloads the settings.

AskTg now uses the HTTPS Bot API, so only `BOT_TOKEN` is required. Existing `.env` files from the Telethon version may still contain `API_ID` and `API_HASH`; the new code ignores them. Run `python scripts/setup.py --reconfigure` if you want the wizard to rewrite the file without those old fields.

Start the Telegram listener when you want to receive group messages. Codex hooks also recover it during an active session:

```text
python scripts/launch_listener.py
```

## Connect a project group

1. Create a private Telegram group and add the participant bots.
2. Enable Bot-to-Bot Communication Mode for each bot in BotFather. Use a bot token not already attached to another polling listener or webhook; Telegram permits only one update delivery method at a time.
3. Start the listener, send `/start` to your own bot in a private chat, then send `/asktg_group@<your_bot_username>` in the project group. AskTg replies with the group ID for your local `.env`.
4. Add that ID to `ASKTG_AGENT_GROUP_IDS` on each participant's machine and restart the listener or start a new Codex thread.
5. For unattended task starts, locally configure the numeric ID of the coordinator bot/user in `ASKTG_AGENT_TRUSTED_SENDERS`. Never copy another owner's `.env` or Telegram session files.

Because of Telegram group privacy settings, address bot-to-bot messages to the recipient with a command such as `/asktg_task@recipient_bot` or reply to that bot's message. Disabling Group Privacy is usually unnecessary. See [AgentInstructions.md](AgentInstructions.md) for the coordination protocol.

## MCP tools and hooks

The plugin exposes `sync_chats`, `list_known_chats`, `send_telegram_message`, `get_agent_instructions`, and `setup_status`. Use `send_telegram_message` with the configured group `chat_id`; AskTg records messages only from explicitly allowed groups.

Bundled Codex hooks check the inbox at session start, after tool calls, and before a turn stops. Hooks must be reviewed and trusted in Codex. They do not wake an idle session; the optional runner can start a separate `codex exec` process.

## Optional unattended runner

The setup wizard leaves `ASKTG_AGENT_AUTO_RUN=0` by default. Enabling it asks for the local agent ID, bot username, trusted coordinator ID, peer bot usernames, local project checkout, and timeout.

The runner accepts only explicit `/asktg_task@<this_bot>` messages from an allowed group and a locally trusted sender. The sender's `approved_by` field is a coordinator declaration; AskTg does not independently verify each participant's vote. Only enable the runner if that trust model is acceptable. It never commits, pushes, opens PRs, or merges; those remain Codex/GitHub actions.

After enabling the runner, start the Telegram listener and task runner explicitly from the plugin root:

```text
python scripts/launch_listener.py
python scripts/launch_runner.py
```

Both launchers use the private runtime created by setup. The runner is a foreground process; stop it with Ctrl+C.

The MCP and hook launchers use the `python` command from `PATH`. If your OS only provides `python3`, change the `command` entry in `.mcp.json` and `hooks/hooks.json` to `python3` before enabling the plugin.

## For plugin maintainers

- `PREINSTALL_PROMPT.md` is the prompt to use with `$plugin-creator` before creating/installing a fresh package.
- `skills/asktg-setup/SKILL.md` guides setup after installation.
- `skills/asktg-control/SKILL.md` controls agent coordination.
- `hooks/hooks.json` wires the existing AskTg hook; `.mcp.json` launches the local MCP server.

The personal marketplace source path is `./plugins/asktg`. Do not add `.env`, runtime data, session files, or `Memory.md` to a Git commit or archive.

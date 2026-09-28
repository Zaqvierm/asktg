---
name: asktg-setup
description: "Set up or troubleshoot AskTg MCP, Telegram bot credentials, approved group access, local hooks, or the optional task runner. Never collect credentials in chat."
---

# Set up AskTg

1. Call `setup_status` first. It reports booleans only and never returns credential values.
2. If the bot token is missing, walk the owner through @BotFather: create a bot with `/newbot` if needed, enable Bot-to-Bot Communication Mode in its settings, and copy its HTTP API token.
3. Start `python scripts/setup.py` in an interactive local terminal. Let the owner enter the token at the wizard's hidden prompt. Never request or accept the token in Codex chat. If an interactive local terminal is unavailable, explain the limitation and give the owner the exact command to run locally.
4. The wizard prepares a per-user Python runtime and installs dependencies outside the plugin tree. It stores credentials outside the plugin and does not start the unattended runner.
5. After credentials are saved, ask the owner to start a new Codex thread so MCP reloads the local configuration.
6. If hooks are not yet trusted, explain what they do and let the owner review them in Codex settings.
7. To connect a project group, have the owner add the bots to a private group, confirm Bot-to-Bot Communication Mode is enabled, and issue `/asktg_group@<bot_username>`. Accept only the group ID that the owner added locally to `ASKTG_AGENT_GROUP_IDS`.
8. Review and trust the bundled Codex hooks only after the owner understands they poll and surface Telegram messages at session start, after tools, and before stopping.

## Optional unattended runner

The runner is disabled by default. Enable it only when the owner explicitly asks, has verified the coordinator's numeric Telegram ID, and accepts that the runner trusts the coordinator's `approved_by` declaration rather than independently verifying votes. Never enable it just because credentials or a group were configured.

If setup changed after the MCP server was already running, instruct the owner to open a new Codex thread. Do not claim that a Telegram bot or group is reachable unless a real connection was made.

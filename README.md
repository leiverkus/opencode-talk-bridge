# opencode-talk-bridge

[![CI](https://github.com/leiverkus/opencode-talk-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/leiverkus/opencode-talk-bridge/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/leiverkus/opencode-talk-bridge?sort=semver)](https://github.com/leiverkus/opencode-talk-bridge/releases/latest)
[![Python](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue)](https://github.com/leiverkus/opencode-talk-bridge/blob/main/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Drive a local [OpenCode](https://opencode.ai) coding agent from
[Nextcloud Talk](https://nextcloud.com/talk/) — a self-hosted chat bridge.

An incoming Talk message is forwarded to a locally-running `opencode serve`
HTTP API; the agent's reply (long output / code as a file attachment) is posted
back into the conversation. The bridge uses **polling** (no webhooks), so it
works on institutional Talk instances where you have no admin access and cannot
register a webhook bot.

> ⚠️ **This bridge runs AI coding-agent actions on your machine, triggered from
> chat in infrastructure you may not control.** Read the
> [Threat model](#threat-model) first. A non-empty user allowlist is mandatory —
> the bridge refuses to start without one.

---

## How it works

```
Nextcloud Talk  ──long-poll──▶  bridge  ──HTTP──▶  opencode serve (localhost)
   (you type)   ◀──post────────  bridge  ◀──SSE────  (agent runs locally)
```

- **Polling**, not webhooks: the bridge long-polls the Talk chat endpoint
  (`lookIntoFuture=1` + `lastKnownMessageId`) using only your app password.
- **OpenCode stays local**: the bridge talks to `opencode serve` over
  `127.0.0.1`. It does **not** start OpenCode — run it yourself, via launchd, or
  via the companion menubar app. The bridge health-checks it and reports when
  it is down.
- **Prompts block; permissions are concurrent**: `POST /session/{id}/message`
  blocks until the turn finishes, so each prompt runs in a worker thread while a
  shared SSE consumer (`/global/event`) routes permission requests back into the
  conversation in real time.

## Requirements

- Python ≥ 3.10, macOS or Linux.
- A Nextcloud account with **Talk** and an **app password**
  (Settings → Security → App passwords) — not your login password.
- A running `opencode serve` (OpenCode ≥ 1.15). Default endpoint
  `http://127.0.0.1:4096`.

## Install

```bash
git clone https://github.com/leiverkus/opencode-talk-bridge.git
cd opencode-talk-bridge
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # drop [dev] for a runtime-only install
cp .env.example .env           # then edit .env
```

The OCS client lives in a separate repo and is pulled in as a **pinned git
dependency** (`nextcloud-talk-core @ …@core-v1.0.0`); the repo is public, so the
install needs no credentials.

## Configure

Edit `.env` (see [`.env.example`](.env.example) for the full list):

| Variable | Required | Purpose |
| --- | --- | --- |
| `NC_URL`, `NC_USER`, `NC_APP_PASSWORD` | ✅ | Nextcloud Talk credentials (app password). |
| `TALK_CONVERSATIONS` | ✅ | Conversation token(s) to watch, or `all`. |
| `ALLOWED_USERS` | ✅ | Comma-separated **user IDs** allowed to issue commands. Empty ⇒ refuses to start. |
| `OPENCODE_URL` | – | OpenCode base URL (default `http://127.0.0.1:4096`). |
| `OPENCODE_USERNAME` / `OPENCODE_PASSWORD` | – | Basic-Auth if your OpenCode server is secured. |
| `OPENCODE_DIRECTORY` | – | Workspace directory for OpenCode sessions. |
| `OPENCODE_MODEL` | – | Default model `providerID/modelID`. |
| `SHARE_WEBDAV_DIR` | – | WebDAV folder (relative to user root) for code/long-output **and TTS** attachments. Created on demand; blank disables attachments. |
| `RESPONSE_STREAMING`, `STREAM_THROTTLE_MS` | – | Live-stream replies via message editing (default on, 1500 ms throttle). |
| `HIDE_TOOL_MESSAGES`, `HIDE_THINKING` | – | Suppress `💻 tool` / `💭 thinking` notices. |
| `BOT_LOCALE` | – | UI language: `de` (default) or `en`. |
| `STT_API_URL` / `STT_API_KEY` / `STT_MODEL` / `STT_LANGUAGE` | – | Whisper-compatible speech-to-text for voice notes. |
| `TTS_API_URL` / `TTS_API_KEY` / `TTS_MODEL` / `TTS_VOICE` | – | OpenAI-compatible text-to-speech for `/tts` replies. |
| `TASK_LIMIT`, `LIST_LIMIT`, `TRACK_BACKGROUND_SESSIONS` | – | Scheduler limit, picker size, background notices. |
| `DB_PATH`, `STATUS_FILE`, `LOG_LEVEL` | – | Storage + logging. |

> **`ALLOWED_USERS` must be the stable user ID** (the login, e.g. `jdoe`), **not
> the display name.** The bridge matches the OCS `actorId` with
> `actorType == "users"`, so guests and bots can never impersonate an allowed
> user even if display names collide.

## Run

```bash
# Validate config + check OpenCode health, then exit:
opencode-talk-bridge --check

# Run the bridge (foreground):
opencode-talk-bridge            # or: python -m opencode_talk_bridge
```

### Commands (in Talk)

Send any message (or a **voice note** / **file**) to prompt OpenCode. The reply
**streams live** into one message as it is generated. Slash-commands:

| Command | Effect |
| --- | --- |
| `/new` | Start a fresh OpenCode session for this conversation. |
| `/session` | Show the current session id. |
| `/sessions` | List & switch recent sessions. |
| `/rename <title>` | Rename the current session. |
| `/detach` | Detach from the current session. |
| `/messages` | Browse messages, then **revert** or **fork**. |
| `/model [providerID/modelID]` | Show, pick, or set the model. |
| `/agent [name]` | Show, pick, or set the agent (e.g. plan/build). |
| `/projects` | Switch the OpenCode project. |
| `/worktree` | Switch the git worktree. |
| `/commands` | Browse & run custom OpenCode commands. |
| `/skills` | Browse & run OpenCode skills. |
| `/mcps` | Enable/disable MCP servers. |
| `/tts` | Toggle spoken (audio) replies (needs `TTS_*` + `SHARE_WEBDAV_DIR`). |
| `/task <min> <prompt>` | Schedule a task (`/task every <min> …` to repeat). |
| `/tasklist` | List & delete scheduled tasks. |
| `/stop` | Abort the current run. |
| `/status` | Show bridge & OpenCode health. |
| `/help` | List commands. |

**No inline buttons** on Talk → every picker is a **numbered list**: reply with
the number. When OpenCode asks **permission** for a dangerous action, reply
**`ja`** (allow once), **`immer`** (allow for this session), or **`nein`** (deny);
agent **questions** are answered by their option number or free text.

Set `BOT_LOCALE=en` for English UI strings (default `de`).

## Run under launchd (macOS)

A user-agent example is in [`deploy/`](deploy/). Edit the paths, then:

```bash
cp deploy/com.leiverkus.opencode-talk-bridge.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.leiverkus.opencode-talk-bridge.plist
# stop / uninstall:
launchctl bootout gui/$(id -u)/com.leiverkus.opencode-talk-bridge
```

Secrets stay in `.env` (read from `WorkingDirectory`), never in the plist.

## Status file (menubar-app contract)

The bridge atomically writes `STATUS_FILE` (JSON) on every state change. A
supervising app (e.g. the Swift menubar app) can poll it. The file is always
valid JSON (temp-write + rename). Schema:

```json
{
  "state": "polling",
  "since": 1748600000,
  "opencode_healthy": true,
  "conversations": ["abcdef12"],
  "last_error": null,
  "version": "0.1.0"
}
```

`state` ∈ `starting` · `polling` · `working` · `opencode_down` · `error` ·
`stopped`. `since` is a Unix timestamp; `conversations` lists watched tokens;
`last_error` is a human-readable string or `null`.

## Threat model

This bridge **executes coding-agent actions on your machine** (file writes,
shell commands via OpenCode), **triggered by chat messages in a Nextcloud Talk
instance you may not administer** (e.g. a university server). Treat that Talk
instance as semi-trusted infrastructure. The trust boundary and mitigations:

- **Access control is the allowlist.** Only `actorType == "users"` IDs in
  `ALLOWED_USERS` can issue commands; every other message is ignored. An empty
  allowlist aborts startup. Anyone who can post as an allowlisted user can run
  code as you — keep the list minimal and the control conversation private.
- **Dangerous actions require confirmation.** OpenCode's permission prompts
  (shell, file writes) are surfaced into Talk and must be answered; nothing
  runs without a `ja`/`immer`. Configure OpenCode's own permission policy
  conservatively as defence in depth.
- **Secrets are never echoed.** The bridge does not post your app password or
  tokens, and permission prompts show only the action kind and a length-capped
  pattern — not raw command arguments that might contain secrets. Be aware that
  OpenCode's **answer text itself** could contain sensitive repo content; it is
  posted into Talk, whose admins can read it.
- **A compromised Talk server** could inject messages appearing to come from an
  allowlisted user. The allowlist mitigates casual misuse, not a fully
  compromised IdP/server. Do not point this at sensitive repos if that is your
  threat model.
- **Local-only OpenCode.** Keep `opencode serve` bound to `127.0.0.1`. If you
  expose it, secure it with `OPENCODE_USERNAME`/`OPENCODE_PASSWORD`.

## Development

```bash
ruff check src tests
ruff format --check src tests
pytest
```

All tests use mocked HTTP for both Talk and OpenCode — no live calls. CI runs
the matrix on Python 3.10–3.13.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT © Patrick Leiverkus

# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-05-31

Feature-parity push toward `grinev/opencode-telegram-bot`, adapted to Talk.

### Added
- **Live response streaming**: the assistant reply is streamed into a single
  Talk message via editing (`PUT`, throttled by `STREAM_THROTTLE_MS`), instead
  of one post at the end. Toggle with `RESPONSE_STREAMING`.
- **Tool & thinking notices** from the SSE stream (`💻 bash`, `💭 …`), each tool
  announced once per turn; toggle with `HIDE_TOOL_MESSAGES` / `HIDE_THINKING`.
- **Agent questions** (`question.asked`) are surfaced into Talk and answered by
  a numbered option or free text.
- **Numbered-text pickers** (Talk has no buttons): `/sessions` (switch),
  `/model` (pick), `/agent` (pick plan/build/…); `/agent <name>` sets directly.
- OpenCode client wrappers for sessions (rename/revert/unrevert/fork), projects,
  worktrees, models, agents, commands, MCP, and question reply/reject.

- **Breadth commands** (Phase 2): `/rename`, `/detach`, `/projects`,
  `/worktree`, `/commands` (run with streaming), `/mcps` (toggle), and
  `/messages` → revert/fork. Projects/worktrees bind a per-conversation
  directory for new sessions.
- **Background-session notifications** when a non-foreground session goes idle
  (`TRACK_BACKGROUND_SESSIONS`).
- **i18n**: user-facing strings localised via `messages.py` (German + English),
  selected by `BOT_LOCALE`.
- **Voice & files** (Phase 3): incoming file/image attachments are inlined into
  the prompt as OpenCode file parts; voice notes are transcribed (STT,
  Whisper-compatible) into the prompt; optional spoken replies (TTS) shared as
  audio, toggled per-conversation with `/tts`. Config: `STT_*`, `TTS_*`.
- **Scheduled tasks** (Phase 3): `/task <min> <prompt>` (or `/task every <min>
  …`) and `/tasklist`; a daemon scheduler fires due tasks, persisted in SQLite.

### Changed
- Internal refactor: unified pending-interaction registry (`pending.py`),
  streaming substrate (`streaming.py`), and typed SSE dispatch (`events.py`).
- `TalkGateway.send` now returns the message id; added `edit`/`download`.

## [0.1.1] - 2026-05-30

### Changed
- File attachments now upload to Nextcloud directly via **WebDAV** (`PUT`,
  creating the target folder on demand) before sharing into the conversation.
  This removes the previous dependency on a desktop sync client having already
  uploaded the file, which could make `share_file` fail with "not found".
- Attachment config simplified to a single `SHARE_WEBDAV_DIR` (the server-side
  folder), replacing `SHARE_DIR` + `SHARE_WEBDAV_ROOT`.

### Added
- `webdav.py`: minimal WebDAV client (reuses the app-password credentials).

## [0.1.0] - 2026-05-30

Initial release.

### Added
- Polling bridge between Nextcloud Talk and a local OpenCode instance — no
  webhooks, works on institutional Talk instances without admin access.
- OpenCode HTTP + SSE client (`opencode.py`), verified against the
  `opencode serve` 1.15 OpenAPI: health, session create/list, blocking prompt,
  abort, global permission reply, and the `/global/event` stream.
- Mandatory user allowlist enforced on the stable OCS `actorId` with
  `actorType == "users"`; the bridge refuses to start with an empty allowlist.
- Permission prompts for dangerous agent actions surfaced into Talk, answered
  with `ja`/`immer`/`nein` and replied via `POST /permission/{id}/reply`.
- SQLite session store mapping each Talk conversation to an OpenCode session,
  model, and last-known-message cursor; persists across restarts.
- Slash-commands: `/new`, `/session`, `/model`, `/stop`, `/status`, `/help`.
- File attachments for long output / code, written to a Nextcloud share folder
  and shared into the conversation instead of posting a large text block.
- Atomic JSON status file as a stable contract for a supervising menubar app.
- CLI entrypoint with `--check` and graceful SIGINT/SIGTERM shutdown.
- launchd user-agent example (`deploy/`), README threat model, and the
  `.env.example` template.
- Test suite (mocked Talk + OpenCode, no live calls) and CI matrix on
  Python 3.10–3.13 with ruff lint + format checks.

### Dependencies
- `nextcloud-talk-core`, pinned to the `core-v1.0.0` git tag.
- `httpx >= 0.27`.

[Unreleased]: https://github.com/leiverkus/opencode-talk-bridge/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/leiverkus/opencode-talk-bridge/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/leiverkus/opencode-talk-bridge/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/leiverkus/opencode-talk-bridge/releases/tag/v0.1.0

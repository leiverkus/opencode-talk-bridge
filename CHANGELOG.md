# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/leiverkus/opencode-talk-bridge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/leiverkus/opencode-talk-bridge/releases/tag/v0.1.0

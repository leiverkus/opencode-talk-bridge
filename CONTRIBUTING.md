# Contributing & maintaining

## Dev setup

```bash
git clone https://github.com/leiverkus/opencode-talk-bridge.git
cd opencode-talk-bridge
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # editable install + ruff/pytest
```

## Checks (what CI runs)

```bash
ruff check src tests           # lint
ruff format --check src tests  # formatting (drop --check to apply)
pytest                         # tests + coverage (pytest-cov)
```

All tests mock both sides (Talk via `nextcloud-talk-core`/httpx, OpenCode via
mocked REST + a fake SSE stream) — **no live calls**. CI runs the matrix on
Python 3.10–3.13. Please keep new code covered and the suite green.

## Layout

```
src/opencode_talk_bridge/
  __main__.py   CLI (--init / --check / run), signals
  config.py     env/.env config (mandatory allowlist lives here)
  opencode.py   OpenCode HTTP + SSE client
  talk.py       Nextcloud Talk gateway (poll/send/edit/share, raw actorId)
  webdav.py     WebDAV upload/download for attachments
  bridge.py     orchestration: poll loop, SSE dispatch, prompt workers
  pending.py    one pending interaction per conversation (perm/question/select)
  streaming.py  live message-edit streaming
  events.py     typed SSE event classification
  permissions.py / commands.py / sessions.py / status.py / scheduler.py
  stt.py / tts.py        voice (optional)
  messages.py   i18n catalog (de/en)
```

## Conventions

- **Code comments in English.** Ruff line length 110; rules in `pyproject.toml`.
- The **`ALLOWED_USERS` allowlist is mandatory** — never add a path that lets
  the bridge act on a message without checking `actor_id`/`actor_type`.
- **Never post raw OpenCode HTTP responses or secrets into Talk.** HTTP errors
  (`OpenCodeError`) get a generic user message; details go to the log only.
- Verify external API assumptions against a live `opencode serve` (`/doc`
  OpenAPI) rather than guessing — see `docs/smoke-test.md`.

## Cutting a release

Releases publish to PyPI automatically via Trusted Publishing on a version tag
(`.github/workflows/publish.yml`). One command set:

```bash
# 1. bump the version in ONE place — pyproject.toml -> version = "X.Y.Z".
#    (__version__ is read from the installed metadata; no second edit needed.)
# 2. move the CHANGELOG "Unreleased" items under "## [X.Y.Z] - <date>" and add
#    the compare links at the bottom.
# 3. ship it:
git commit -am "Release X.Y.Z: <summary>"
git tag -a vX.Y.Z -m "opencode-talk-bridge X.Y.Z"
git push origin main && git push origin vX.Y.Z      # -> publish.yml builds + publishes to PyPI
gh release create vX.Y.Z --title "vX.Y.Z — <title>" --notes "<notes>"
```

The publish workflow **guards** that the tag matches `pyproject.toml` and runs
`twine check`, so a version mismatch fails fast and never reaches PyPI. First-time
PyPI/Trusted-Publisher setup is documented in
[`docs/publishing.md`](docs/publishing.md).

## Reporting

Issues and PRs welcome. For anything touching the security model (allowlist,
permission flow, what gets posted to Talk), please call it out explicitly in the
PR description.

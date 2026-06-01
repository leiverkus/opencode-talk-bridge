<!-- Thanks for contributing! Keep PRs focused; see CONTRIBUTING.md. -->

## What & why

<!-- What does this change, and why? Link any issue: Fixes #123 -->

## Checklist

- [ ] `ruff check src tests` and `ruff format --check src tests` pass
- [ ] `pytest` passes; new behaviour has tests (both sides mocked, no live calls)
- [ ] CHANGELOG "Unreleased" updated if user-facing
- [ ] Docs / `.env.example` updated if config, commands, or behaviour changed

## Security model

<!-- Required if this touches the allowlist, permission/question flow, or what
gets posted to Talk. Otherwise write "n/a". -->

- [ ] Does not let the bridge act on a message without an allowlist check
- [ ] Does not post secrets or raw OpenCode/Nextcloud responses into Talk

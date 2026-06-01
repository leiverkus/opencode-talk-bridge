# Security Policy

`opencode-talk-bridge` runs AI coding-agent actions (file writes, shell commands
via OpenCode) on your machine, triggered by chat messages in a Nextcloud Talk
instance you may not administer. Security is therefore a primary concern — see
the [threat model](README.md#threat-model) for the trust boundary and built-in
mitigations (mandatory allowlist on stable user id, permission prompts, no secret
or server-text leakage into chat).

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private vulnerability reporting:
[**Report a vulnerability**](https://github.com/leiverkus/opencode-talk-bridge/security/advisories/new)
(Security tab → "Report a vulnerability"). This opens a private advisory visible
only to you and the maintainer.

If private reporting is unavailable, open a minimal public issue asking the
maintainer to open a private channel — **without** technical details.

Please include: affected version, a description, reproduction steps, and the
impact you see. A proof of concept is helpful but not required.

## Scope

**In scope** — the bridge's own security model:
- allowlist bypass (acting on a message from a non-allowlisted `actorId`/`actorType`),
- the permission/question approval flow being skippable or spoofable,
- leakage of secrets or raw OpenCode/Nextcloud responses into a Talk message,
- the `.env` / app password handling, the status file, or the SQLite store
  exposing credentials.

**Out of scope** — issues in dependencies or the surrounding system:
- OpenCode itself, Nextcloud / Talk, or `nextcloud-talk-core`,
- you exposing `opencode serve` on a public interface (keep it on `127.0.0.1`),
- misconfiguration (e.g. an over-broad `ALLOWED_USERS`, a shared bot account).

Report those to the respective upstream projects.

## Supported versions

This is a young project; only the **latest released version** receives security
fixes. Pin a version you trust and upgrade promptly when an advisory is published.

## Response

Best effort by a small maintainer team. Expect an acknowledgement within about a
week, and a fix or mitigation as soon as practical for confirmed, in-scope
issues. Fixes ship as a new release with a CHANGELOG entry; credit is given
unless you prefer otherwise.

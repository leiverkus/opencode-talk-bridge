# Publishing to PyPI

Releases publish automatically to [PyPI](https://pypi.org/project/opencode-talk-bridge/)
by [`.github/workflows/publish.yml`](../.github/workflows/publish.yml) on every
`vX.Y.Z` tag, using **Trusted Publishing (OIDC)** — no API token is stored in the
repository.

The canonical "how to cut a release" steps live in
[CONTRIBUTING.md](../CONTRIBUTING.md#cutting-a-release). This file documents how
the publishing is *wired up*.

## How it works

On a tag push the workflow:

1. **guards** that the tag (`vX.Y.Z`) matches the `pyproject.toml` version —
   fails fast on a mismatch, so nothing wrong reaches PyPI;
2. builds the sdist + wheel and runs `twine check` (validates the README renders
   on the PyPI page);
3. publishes via OIDC to the `pypi` GitHub environment — no secrets.

`__version__` is read from the installed package metadata, so the version has a
single source of truth: `pyproject.toml`.

## Trusted Publisher configuration (already set up)

The PyPI project is configured with a Trusted Publisher pointing at this repo:

| Field | Value |
| --- | --- |
| PyPI Project Name | `opencode-talk-bridge` |
| Owner | `leiverkus` |
| Repository name | `opencode-talk-bridge` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

To reconfigure (e.g. transfer ownership), edit it under PyPI → the project →
*Manage → Publishing*. If you rename the workflow file or the `pypi` environment,
update this Trusted Publisher to match, or OIDC will reject the publish.

(Optional) In GitHub → Settings → Environments, give the `pypi` environment a
required-reviewer rule so each publish needs a human approval.

## Local dry run

```bash
python -m build
python -m twine check dist/*
```

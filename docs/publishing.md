# Publishing to PyPI

Releases are published automatically by
[`.github/workflows/release.yml`](../.github/workflows/release.yml) on every
`vX.Y.Z` tag, using **PyPI Trusted Publishing (OIDC)** — no API token is stored
in the repository.

## One-time PyPI setup (do this once)

Because the project does not exist on PyPI yet, register a **pending publisher**;
the first tagged build will create the project and publish it.

1. Create / sign in to a [PyPI](https://pypi.org/) account.
2. Go to **Account settings → Publishing →
   [Add a pending publisher](https://pypi.org/manage/account/publishing/)**.
3. Fill in exactly:
   | Field | Value |
   | --- | --- |
   | PyPI Project Name | `opencode-talk-bridge` |
   | Owner | `leiverkus` |
   | Repository name | `opencode-talk-bridge` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |
4. Save.

(Optional) In GitHub → Settings → Environments, create an environment named
`pypi` and add a required-reviewer protection rule, so a human approves each
publish.

## Cutting a release

Same flow as before — the tag now also triggers the PyPI publish:

```bash
# bump version in pyproject.toml and src/opencode_talk_bridge/__init__.py,
# update CHANGELOG, commit, then:
git tag -a vX.Y.Z -m "opencode-talk-bridge X.Y.Z"
git push origin main && git push origin vX.Y.Z
gh release create vX.Y.Z --title "…" --notes "…"   # GitHub release (separate)
```

On the tag push, the workflow:
1. **guards** that the tag matches the `pyproject.toml` version (fails fast on a mismatch),
2. builds the sdist + wheel and runs `twine check`,
3. publishes to PyPI via OIDC (no secrets).

After the **first** successful publish, `uv tool install opencode-talk-bridge`
(or `pipx install opencode-talk-bridge`) works without a git URL — update the
README install command accordingly.

## Local dry run

```bash
python -m build
python -m twine check dist/*
```

`twine check` validates that the README renders on the PyPI page.

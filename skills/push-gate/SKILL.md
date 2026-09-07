---
name: push-gate
description: Pre-push privacy and hygiene gate for git repositories. Use when preparing to push a public or shared repo, when asked to audit outgoing commits for secrets/PII/owner paths, or when adopting the gate in a new repository (Confold, Glanvu, md4lp, ...).
---

# push-gate

Read-only gate that audits the outgoing commit range (`@{upstream}..HEAD`)
before a push. Shared logic, local configuration: the detector lives here
(refined once, every consuming repo benefits); each repo carries only its
3-line hook and its allowlist config.

## What it detects

| Detector | Catches | Notes |
|---|---|---|
| secrets | AWS/ASIA keys, GitHub token family, GitLab/Slack/OpenAI/Google key shapes, private key blocks (incl. encrypted), JWTs, assigned secret literals | conservative regex set; generic entropy is gitleaks' domain (server-side net) |
| pii | Spanish DNI/NIF, NIE, IBAN-ES, +34 mobile phones (hyphen/space/case variants) | tuned for expediente-adjacent repos |
| owner-paths | `/Users/<name>/`, `/home/<name>/` absolute paths | generic doc-example usernames (foo/bar/test/…) are exempt; deterministic fixtures use `/fixture/...` |
| attachments | add-like changes (added/copied/renamed) to files with binary extensions | deletions and in-place edits of previously pushed files are not flagged |
| protected-paths | any change to glob-matched paths (e.g. `WIP/evidence/**`) | checked on both sides of renames |

Every finding is blocking; the pressure valve is the repo's allowlist
config, never silence. Bypass once with `git push --no-verify` and leave
the reason in the session note. Matched values are redacted in reports
(first characters only); other metadata (paths, refs) is reported as-is.

## Auditing a repo (no installation needed)

```bash
~/.agents/skills/push-gate/scripts/pre_push_audit.py --repo-root /path/to/repo
```

Add `--json` for machine-readable output, `--range origin/main..HEAD` when
no upstream is configured. Exit codes: 0 clean, 1 blocking findings,
2 operational failure.

## Adopting the gate in a repository

1. Copy `templates/pre-push` to `<repo>/.githooks/pre-push` (executable).
2. Copy `templates/push-gate.json` to `<repo>/push-gate.json` and tune the
   allowlists to that repo's synthetic fixtures and vendored sources.
3. `git config core.hooksPath .githooks`
4. Optionally copy `templates/.gitleaks.toml` and
   `templates/gitleaks.yml` (to `<repo>/.github/workflows/`) for the
   server-side net.

agent-brain itself runs the same steps (dogfooding): its hook calls the
script from its own tree, so refining the detector here upgrades every
consumer after a `git pull`.

## Config reference (`push-gate.json`)

```json
{
  "schema_version": "push-gate/config-v1",
  "allow_paths": ["tests/fixtures/", "model/SOURCES/legal/"],
  "allow_strings": ["AKIA000000000000EXAMPLE"],
  "disabled_detectors": [],
  "protected_paths": ["WIP/evidence/**"]
}
```

- `allow_paths`: path prefixes exempt from line-scan and attachment checks.
- `allow_strings`: exact matched values exempt from secrets/PII/owner-path
  findings (for deliberate synthetic test tokens).
- `disabled_detectors`: detector names turned off for this repo (avoid;
  prefer allowlists).
- `protected_paths`: fnmatch globs; any diff touching them fails.

Script reference: `scripts/TOOL.pre-push-audit.md`.

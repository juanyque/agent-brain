# pre_push_audit.py

Read-only pre-push gate. Audits a commit range for secrets, Spanish PII,
owner-specific absolute paths, unexpected binary attachments, and protected
paths. Never mutates the repository, the index, or the worktree.

## Usage

```bash
python3 pre_push_audit.py [--repo-root DIR] [--range RANGE]
                          [--config PATH] [--json]
```

- Default range: `@{upstream}..HEAD`; with no upstream configured the tool
  fails (exit 2) and asks for an explicit `--range`.
- Default config: `<repo-root>/push-gate.json` (missing file = empty config:
  everything detected blocks; see `SKILL.md` for the config reference).
- Exit codes: `0` clean, `1` blocking findings, `2` operational failure.
- Matched values are redacted in both human and JSON reports (first
  characters only); other metadata (paths, refs) is reported as-is.

## Behavior

- Line findings come from added lines of the unified diff (`-U0`); binary
  files contribute no lines, so attachment findings rely on add-like
  statuses (added/copied/renamed) plus the path extension from
  `--name-status -z`. The wrapper pins `core.quotepath=false`,
  `diff.noprefix=false`, and the `a/` `b/` diff prefixes so repository
  configuration cannot reshape the parsed headers; `--text` forces hunks
  even for files marked `-diff` in `.gitattributes`.
- The range is audited **per commit** (each against its own parent), not as
  one endpoint diff, so content introduced and later removed inside the
  range is still caught (it ships in pushed history). Findings carry the
  commit OID (rendered `path:line @abc12345`).
- `--range` endpoints are resolved to validated commit OIDs (SHA-1 or
  SHA-256) via `git rev-parse --verify` before any diff is produced; an
  all-zero base (new remote ref) audits the ref's full history from the
  empty tree, computed read-only via `git hash-object -t tree` (no object
  is written). Anything that does not resolve fails closed (exit 2).
- Changed paths on BOTH sides of renames are checked against
  `protected_paths` and scanned for PII and owner-path shapes in their
  names (kinds suffixed `-in-path`); allowlisted path prefixes are exempt
  from name scans.
- `allow_paths` exempts whole path prefixes from line, attachment, and
  path-name checks.
- `allow_strings` exempts a matched value when the allowed string equals
  it or occurs inside the matched span (assignment matches wrap their
  token).
- `disabled_detectors` turns off a detector by name; prefer allowlists.
- `protected_paths` are fnmatch globs checked against every changed path
  from `--name-status`, regardless of allowlists.

## Log / output

- Human report on stdout by default; `--json` emits
  `{"repo", "range", "findings": [{detector, kind, path, line, match,
  commit}]}` (match is the redacted value; commit is the OID that first
  introduced the finding).
- No log files are written; hooks should let git capture stdout/stderr.

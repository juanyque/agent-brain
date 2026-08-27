# source_scheduler.py

## Purpose
- Decide, for source ingestion (`RULES-OPTIONAL-CAPABILITIES.common.md` -> "Source
  ingestion"), which registered sources are due, not due, or blocked.
- Decide whether the capability is activated for the brain at all (a real wikilink or
  Markdown link to `sources.registry`, resolved by exact target basename, anywhere in
  `WIP/WIP.md`).
- Record the watermark after a source has actually been investigated.

## Scope
Source ingestion is brain-scoped, not project-scoped: every enabled registry entry is
evaluated every session, regardless of the working directory a session opens in. `--cwd`
(on `list-due`, and threaded through automatically at session open) is unrelated to this:
it only selects which environment profile applies, exactly like `profile_context.py`'s own
selector. It never scopes which sources are evaluated.

## Decision model
- `due`: the cadence window has elapsed (or the source is `Check cadence (days): always`).
  Safe to investigate.
- `not due` (silent): checked recently enough. Nothing is surfaced.
- `blocked`: something about the source, its descriptor, its type guide, or the registry
  itself could not be determined safely, so it is reported and skipped rather than
  investigated. Causes include: the registry is missing, symlinked, unreadable (any
  `OSError`, not only a decode failure), or not valid UTF-8; a slug is registered more
  than once -- including one `enabled` and one `disabled` section for the same slug, or
  a registry entry with a duplicated field (e.g. two `Descriptor:` lines); a registry
  `Descriptor:` field is missing or does not name this slug; the descriptor is missing,
  symlinked, unreadable, not valid UTF-8, or has a duplicated field; the source type is
  malformed, or its `SOURCE_TYPES/<type>.md` guide is missing, symlinked, unwritten, or
  itself unreadable; `Requires capability` is missing, malformed, or unroutable by the
  active environment profile; `Locator` or `Last status` is missing; or
  `Check cadence (days)` / `Last checked` is missing or malformed (including under
  `always`, which still validates a non-sentinel `Last checked` date). Fail-closed by
  design: an indeterminable case is never guessed open. `list-due` itself also checks
  activation (a real, local, rendered link to `sources.registry`) before evaluating
  anything -- see "Usage" below.

Capability validation is static only (a profile-document lookup, no live provider call).
The subagent that actually investigates a due source resolves the capability live (e.g.
via `profile_context.py`) and reports `degraded` if that live resolution fails.

## Usage

### List due/blocked sources
```bash
python3 ~/.agents/skills/brain/scripts/source_scheduler.py --brain-root . list-due
python3 ~/.agents/skills/brain/scripts/source_scheduler.py --brain-root . list-due --json
```
`list-due` checks activation itself (a real link to `sources.registry` anywhere in
`WIP/WIP.md`) before evaluating anything; a dormant brain reports `dormant: ...` (or
`{"activated": false, "decisions": []}` under `--json`) rather than dispatching sources
that were never opted in. `--json`'s shape is always
`{"activated": <bool>, "decisions": [...]}`.

### Record a completed check (dry-run by default)
```bash
python3 ~/.agents/skills/brain/scripts/source_scheduler.py mark-checked \
  --brain-root . --source <slug> --status ok
```
`--brain-root` may appear before or after the subcommand name. Add `--apply` to actually
write:
```bash
python3 ~/.agents/skills/brain/scripts/source_scheduler.py mark-checked \
  --brain-root . --source <slug> --status ok --apply
```

### Test with a fixed date
```bash
python3 ~/.agents/skills/brain/scripts/source_scheduler.py --brain-root . list-due --date 2026-08-27
```

## Safety model
- `list-due` is fully read-only.
- `mark-checked` is dry-run by default; it only prints the plan. `--apply` is required to
  write.
- The source slug is validated before any path is constructed; a slug outside
  `^[a-z0-9][a-z0-9._-]*$` (e.g. containing `/`, or not starting with a letter or digit)
  is rejected, not resolved. This blocks path separators; it does not forbid a literal
  `.` or `..` substring inside an otherwise valid slug.
- A descriptor that is a symlink, or whose parent inside the brain is a symlink, is
  rejected rather than followed. The same no-follow check applies to a source's type
  guide under `SOURCE_TYPES/`.
- The write is atomic: a uniquely named temp file created with `O_EXCL` in the same
  directory (never a predictable sibling, so it can't be pre-planted as a symlink),
  then a rename. The original file's mode is preserved explicitly.
- `Last checked:` is the watermark of the last *successful* check. `mark-checked --status
  degraded` updates `Last status:` but deliberately leaves `Last checked:` untouched, so a
  failed attempt never advances the "safe to skip up to here" boundary and the source
  stays due for retry.
- Every `mark-checked` run prints to console and writes `source_scheduler.log` next to
  this script (a runtime artifact, gitignored, not committed).

## Registry/descriptor parsing contract
- `sources.registry.md` entries: `### <slug>` heading, then `- Status:`, `- Type:`,
  `- Descriptor:`, `- Purpose:` fields. Only `Status: enabled` entries are considered.
  `Descriptor:` is a validated cross-check, not a redirect: the descriptor path is
  always the deterministic `sources.<slug>.md`, and the field must resolve to that
  same slug or the entry is blocked -- it never picks a different file.
- `sources.<slug>.md` descriptor fields read by this script: `Type:` (via the registry
  entry, not the descriptor), `Requires capability:`, `Locator:`, `Check cadence (days):`,
  `Last checked:`, `Last status:`. `Locator` and `Last status` must be present (their
  content is otherwise the investigating subagent's / `mark-checked`'s concern, not
  validated here beyond presence).
- `Check cadence (days): always` is the sentinel for a source that is inherently
  time-sensitive per session (a calendar), represented internally as `cadence_days == 0`.
- `Last checked:` sentinels meaning "never checked": empty, `not checked`, or `none`.
- A field value may be written as inline code (`` `issues.search` ``); one surrounding
  pair of backticks is stripped before parsing.

## Known limitations
- Capability validation only checks that the active environment profile routes the named
  capability; it does not check provider readiness or secrets. A source can be `due`
  here and still turn out `degraded` once the subagent actually tries to reach it live.
- A brain with no environment profile configured at all blocks every source that
  declares a `Requires capability` (which is every source) -- see
  `docs/runtime-profiles.md` for setting one up.
- Two concurrent `mark-checked --apply` calls for the same source are not coordinated:
  each write is atomic and self-consistent, but whichever completes its rename last
  wins. Not expected in normal use (nothing else runs `mark-checked` for a source
  outside its own investigation), so no locking is implemented.

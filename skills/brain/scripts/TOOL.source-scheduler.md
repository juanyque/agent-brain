# source_scheduler.py

## Purpose
- Decide, for source ingestion (`RULES-OPTIONAL-CAPABILITIES.common.md` -> "Source
  ingestion"), which registered sources are due, not due, or blocked.
- Decide whether the capability is activated for the brain at all (a direct link to
  `sources.registry` anywhere in `WIP/WIP.md`).
- Record the watermark after a source has actually been investigated.

## Scope
Source ingestion is brain-scoped, not project-scoped: every enabled registry entry is
evaluated every session, regardless of the working directory a session opens in.

## Decision model
- `due`: the cadence window has elapsed (or the source is `Check cadence (days): always`).
  Safe to investigate.
- `not due` (silent): checked recently enough. Nothing is surfaced.
- `blocked`: something about the source could not be determined safely, so it is reported
  and skipped rather than investigated. Causes: missing/symlinked descriptor, missing or
  unwritten source type (no `SOURCE_TYPES/<type>.md` guide), a missing or malformed
  `Requires capability` field, a capability the brain's active environment profile
  cannot route, or a missing/malformed `Check cadence (days)` / `Last checked` field.
  Fail-closed by design: an indeterminable case is never guessed open.

Capability validation is static only (a profile-document lookup, no live provider call).
The subagent that actually investigates a due source resolves the capability live (e.g.
via `profile_context.py`) and reports `degraded` if that live resolution fails.

## Usage

### List due/blocked sources
```bash
python3 ~/.agents/skills/brain/scripts/source_scheduler.py --brain-root . list-due
python3 ~/.agents/skills/brain/scripts/source_scheduler.py --brain-root . list-due --json
```

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
  `^[a-z0-9][a-z0-9._-]*$` (e.g. containing `/` or `..`) is rejected, not resolved.
- A descriptor that is a symlink, or whose parent inside the brain is a symlink, is
  rejected rather than followed.
- The write is atomic (temp file + rename), never a partial in-place edit.
- `Last checked:` is the watermark of the last *successful* check. `mark-checked --status
  degraded` updates `Last status:` but deliberately leaves `Last checked:` untouched, so a
  failed attempt never advances the "safe to skip up to here" boundary and the source
  stays due for retry.
- Every `mark-checked` run prints to console and writes `source_scheduler.log` next to
  this script (a runtime artifact, gitignored, not committed).

## Registry/descriptor parsing contract
- `sources.registry.md` entries: `### <slug>` heading, then `- Status:`, `- Type:`,
  `- Descriptor:`, `- Purpose:` fields. Only `Status: enabled` entries are considered.
- `sources.<slug>.md` descriptor fields read by this script: `Type:` (via the registry
  entry, not the descriptor), `Requires capability:`, `Check cadence (days):`,
  `Last checked:`, `Last status:`.
- `Check cadence (days): always` is the sentinel for a source that is inherently
  time-sensitive per session (a calendar), represented internally as `cadence_days == 0`.
- `Last checked:` sentinels meaning "never checked": empty, `not checked`, or `none`.

## Known limitations
- Capability validation only checks that the active environment profile routes the named
  capability; it does not check provider readiness or secrets. A source can be `due`
  here and still turn out `degraded` once the subagent actually tries to reach it live.
- A brain with no environment profile configured at all blocks every source that
  declares a `Requires capability` (which is every source) -- see
  `docs/runtime-profiles.md` for setting one up.

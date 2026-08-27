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
  investigated. Causes include: the registry is missing, symlinked (leaf or any parent
  directory component), unreadable (any `OSError`, not only a decode failure), or not
  valid UTF-8; a slug is registered more than once -- including one `enabled` and one
  `disabled` section for the same slug, or two `disabled` sections, or a registry entry
  with a duplicated field (e.g. two `Descriptor:` lines); a `Status:` field is missing or
  holds any value other than exactly `enabled`/`disabled` (a typo is a fourth,
  indeterminable state, not a silent opt-out); a registry `Descriptor:` field
  is missing, or does not name exactly this slug (naming this slug PLUS a second,
  conflicting target is also rejected -- the field must be unambiguous, not merely
  "matches somewhere"); the descriptor is missing, symlinked (leaf or parent),
  unreadable, not valid UTF-8, or has a duplicated field; the source type is
  malformed, or its `SOURCE_TYPES/<type>.md` guide is missing, symlinked, unwritten,
  empty/whitespace-only, or itself unreadable (including an unreadable
  `SOURCE_TYPES/` directory itself, not only the guide file); `Requires capability`
  is missing, malformed, or unroutable by the active environment profile; `Locator`
  or `Last status` is missing; a leaf path (registry, descriptor, or guide) resolves
  to something other than a regular file (a FIFO, device, or directory); or
  `Check cadence (days)` / `Last checked` is missing, malformed, or arithmetically
  out of range (a `Last checked` near `date.max` plus even a small cadence overflows
  the representable date range, and is blocked rather than crashing) -- including
  under `always`, which still validates a non-sentinel `Last checked` date. A
  duplicate slug or a duplicate field within one entry (e.g. two `Descriptor:`
  lines) is reported regardless of that entry's `Status:`, including two `disabled`
  sections. Fail-closed by design: an indeterminable case is never guessed open.
  `list-due` itself also checks activation (a real, local, rendered link to
  `sources.registry` -- a wikilink requires an actual closing `]]`, not just the
  opening `[[` -- excluding HTML comments -- an unclosed comment runs to end of
  document, matching CommonMark's own raw-HTML-block semantics -- fenced or inline
  code of any backtick/tilde run length (code-span delimiters must be exactly
  matching, maximal runs; a shorter run does not close a longer one, and both the
  opener and closer may carry CommonMark's 0-3-space indentation allowance), and
  external (any URI scheme, not only `scheme://`) or protocol-relative URLs, with an
  optional CommonMark title tolerated after the destination and a backslash-escaped
  ASCII punctuation character in the destination unescaped before comparison) before
  evaluating anything -- see "Usage" below. A malformed or unresolvable `--cwd` (e.g.
  a symlink loop) is likewise blocked rather than raised, both from the CLI and from
  `capability_routes()` internally.

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
- Both subcommands fail cleanly on malformed input or environment errors -- an invalid
  `--date` or `--cwd` (e.g. a symlink loop), or a write failure `mark-checked --apply`
  hits mid-operation (e.g. a non-writable `SOURCES/` directory) -- with a diagnostic
  and a nonzero exit, never an uncaught Python traceback.
- The source slug is validated before any path is constructed; a slug outside
  `^[a-z0-9][a-z0-9._-]*$` (e.g. containing `/`, or not starting with a letter or digit)
  is rejected, not resolved. This blocks path separators; it does not forbid a literal
  `.` or `..` substring inside an otherwise valid slug.
- Every read (registry, descriptor, type guide, `WIP.md`) opens each path component --
  not just the leaf -- through a directory-fd chain rooted at the brain: each parent
  directory between the brain root and the file is opened with `O_DIRECTORY|O_NOFOLLOW`
  relative to the already-open previous directory's descriptor, then the leaf is opened
  with `O_NOFOLLOW | O_NONBLOCK` relative to that descriptor, and the result is
  rejected unless it is a regular file. A symlink anywhere in the path -- leaf or
  any parent component -- is rejected rather than followed; `O_NONBLOCK` closes a
  separate gap where a FIFO with no writer would otherwise hang the open
  indefinitely, before the regular-file check ever ran; and a swap of any
  component after an earlier check but before this open cannot redirect an
  already-open descriptor.
- The write uses the same directory-fd chain to open the parent, `lstat`s the leaf
  (`follow_symlinks=False`, rejecting anything but a regular file -- a raced
  post-read symlink swap must not have its target's mode silently copied onto the
  replacement) to capture the original mode, then creates a uniquely named temp
  file with `O_EXCL` relative to that descriptor (never a predictable sibling
  path, so it can't be pre-planted as a symlink), then `os.rename()` (not
  `os.replace()`, which does not support `dir_fd` on every platform this runs on)
  relative to the same descriptor for both source and destination. The original
  file's mode is preserved explicitly.
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
- A field line may have one or more spaces after the leading `-`; `mark-checked`'s
  watermark-line matching accepts the same range, not just a single literal space, so
  a source `decide_source()` returns as due is always one it can also write.

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

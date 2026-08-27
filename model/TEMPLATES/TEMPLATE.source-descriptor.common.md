---
tags: [wip, source-ingestion]
---
<!-- content-boundary: {"kind":"optional-capability","capability":"source-ingestion","startup":"excluded"} -->
<!-- content-boundary: {"kind":"template","template_id":"source-descriptor","rules":["model/RULES-OPTIONAL-CAPABILITIES.common.md"],"lifecycle_policy":false} -->
# Source: <source-slug>

## Summary

- Source key: `<source-slug>`
- Type: <source-type, matching a `SOURCE_TYPES/<type>.md` guide>
- Status: enabled
- Purpose: <what this source is checked for, and why>

## What to look for

- <concrete signal 1, e.g. "unclosed items assigned to me">
- <concrete signal 2>

Deep-read `SOURCE_TYPES/<type>.md` for the general guidance this type of source
needs; list only what is specific to this particular source above.

## Access

- Requires capability: <generic capability the environment profile resolves, e.g.
  `issues.search`; see `docs/runtime-profiles.md`>
- Locator: <exactly what to read within that capability: a query, a mailbox and label, a
  list of channels, a URL — never the concrete tool or endpoint, the resolved provider
  already owns that>

If the named capability cannot be resolved (missing, unroutable, or the subagent's live
resolution fails at investigation time), the source is `degraded` or blocked, never
guessed open.

## Schedule

- Check cadence (days): 1
- Last checked: not checked
- Last status: not checked

Use `always` instead of a number for a source type that is inherently time-sensitive per
session rather than "changed since last check" (see `SOURCE_TYPES/calendar.md`).

Allowed status values: `ok`, `no_activity`, `degraded`. `source_scheduler.py mark-checked`
owns the last two fields — never edit them by hand. `degraded` never advances
`Last checked:`; only `ok`/`no_activity` do.

## Capture

- Raw capture: `INBOX/sources/<source-slug>/`
- Triage: on request (`/brain revisar fuentes`) or during ordinary session work.

## Next step

- <smallest useful action, or "none" once the source is running normally>

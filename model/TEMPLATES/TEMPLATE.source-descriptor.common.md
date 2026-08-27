---
tags: [wip, source-ingestion]
---
<!-- content-boundary: {"kind":"optional-capability","capability":"source-ingestion","startup":"excluded"} -->
<!-- content-boundary: {"kind":"template","template_id":"source-descriptor","rules":["model/RULES-OPTIONAL-CAPABILITIES.common.md"],"lifecycle_policy":false} -->
# Source: <source-slug>

## Summary

- Source key: `<source-slug>`
- Type: <source-type, matching a `SOURCE_TYPES/<type>.common.md` guide>
- Status: enabled
- Repository root: `<canonical-project-root>`
- Purpose: <what this source is checked for, and why>

## What to look for

- <concrete signal 1, e.g. "unclosed items assigned to me">
- <concrete signal 2>

Deep-read `SOURCE_TYPES/<type>.common.md` for the general guidance this type of source
needs; list only what is specific to this particular source above.

## Schedule

- Check cadence (days): 1
- Last checked: not checked
- Last status: not checked

Use `always` instead of a number for a source type that is inherently time-sensitive per
session rather than "changed since last check" (see `SOURCE_TYPES/calendar.common.md`).

Allowed status values: `ok`, `no_activity`, `degraded`. `source_scheduler.py mark-checked`
owns the last two fields — never edit them by hand.

## Capture

- Raw capture: `INBOX/sources/<source-slug>/`
- Triage: on request (`/brain revisar fuentes`) or during ordinary session work.

## Next step

- <smallest useful action, or "none" once the source is running normally>

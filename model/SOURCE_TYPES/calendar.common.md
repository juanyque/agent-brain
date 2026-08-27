# Calendar
<!-- content-boundary: {"kind":"source-type","owner":"model/SOURCE_TYPES/SOURCE_TYPES.common.md"} -->

## What this covers

A personal or shared calendar that can be queried for events on a given day. Vendor-agnostic:
this guide applies regardless of which specific calendar provider a project's descriptor
names.

## Why this type is special

Every other source type is checked for what changed since the last check. A calendar isn't
— it's inherently time-sensitive *within* a single day, so "was it checked yesterday" is the
wrong question. A calendar source's descriptor should set `Check cadence (days): always`
(see `RULES-OPTIONAL-CAPABILITIES.common.md` → "Due-ness and the watermark" and
`source_scheduler.py`'s cadence handling), so it is always due, every session, regardless of
`Last checked`.

## What to look for

- The remaining events for today, from the current time to end of day, in chronological
  order — time, title, and attendees/location only if that detail is actually useful to
  surface.
- Resolve times in the user's configured timezone. Never assume UTC or the invoking host's
  local timezone silently if the two could differ.

## How to summarize

Always report, even when there is nothing left today — "no more events today" is itself the
correct, worth-showing answer here. This is a live agenda, not a change-diff: the usual
`no_activity` convention (quiet unless something changed) does not apply to this type.

## Failure signals

- Calendar API/MCP unreachable, or authentication expired → `degraded`, with a one-line
  reason. Never silently present an empty agenda as "no more events today" when the real
  cause is that the calendar couldn't be read at all.

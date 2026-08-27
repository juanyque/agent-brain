# Task tracker
<!-- content-boundary: {"kind":"source-type","owner":"model/SOURCE_TYPES/SOURCE_TYPES.common.md"} -->

## What this covers

Systems that track work items with a lifecycle (open/in-progress/closed), assignment, and
relationships between items (task trackers, issue trackers, and similar). Vendor-agnostic:
this guide applies regardless of which specific tool a project's descriptor names.

## What to look for

- An "assigned to me" view, kept separate from a "backlog I report/own" view — an item can
  appear in either, both, or neither; don't conflate them.
- Explicit dependency relationships between items (blocked-by / depends-on) — model these as
  a real graph when they matter, don't assume the tracker's default ordering reflects them;
  a refresh can reveal real dependencies the flat view never surfaced.
- A tracker-internal rank/priority field, when the tool has one, names the next relevant
  item more reliably than other fields — but it must be queried explicitly and refreshed,
  since it goes stale quickly and can't be inferred from anything else.
- Before treating a new item as new work, search by keyword and by "children of the
  relevant parent/epic" first — this avoids duplicating work that's already tracked
  elsewhere under different wording.
- Investigation work that produces follow-on implementation items is an expected pattern,
  not scope creep — don't flag it as such.

## How to summarize

- An item closed as "won't do" (rather than resolved) can represent a legitimate watcher —
  something to keep an eye on externally rather than active work — and should be treated
  like any other terminal state: out of the active backlog, not a pending concern.
- A legitimate external blocker (a dependency on another team, or a time-based gate such as
  "N days of stable data") is not neglect and doesn't need chasing — document it as a gate
  and revisit on a normal cadence.
- Locally-cached status/points/sprint fields can drift from the real system in as little as
  ~12 days — prefer a full resync over trusting an old snapshot when it matters.

## Failure signals

- Status or assignee changed between two consecutive reads with no action of the
  investigating agent in between — a low-confidence signal (unclear cause: system
  automation? another session or person acting in parallel?) that must be reported to the
  user, never silently assumed or "corrected."
- Reading an item without restricting fields can hit size limits on items with a long
  comment history — read filtered by field by default, not the full object.
- A documented fallback path (an alternate CLI or client) that turns out not to be
  installed or configured when actually needed is not a real fallback — verify it works
  before depending on it, don't assume a documented path is a live one.

## Writing gotchas (only if the subagent also writes back)

Source ingestion at session open is read-only by default (`RULES-OPTIONAL-CAPABILITIES.common.md`
→ "Investigation behavior"): the automatic, unattended investigation this guide otherwise
describes never writes to the tracker. This section applies only to a separately
authorized write-back workflow (e.g. an explicit `ingesta <fuente>` request the user
confirms interactively, or a dedicated write task) — never to the passive session-open
check.

- The echo from a first create/comment call can double-escape line breaks (the content
  comes back with literal escape sequences); a subsequent update call on the same item can
  render correctly. Never trust the first call's echo for multi-line content — verify by
  reading it back afterward.
- A checklist written as plain markdown can silently degrade to a flat, non-interactive
  list (more likely when one line mixes a checkbox with inline code formatting) — verify by
  re-reading in the system's native rich rendering after writing, and repair with a
  structural edit if it degraded.
- A different client (e.g. a CLI) accepting the same nominal format can render it fully
  literally (headings/bold/code shown as raw punctuation) — format fidelity is not uniform
  across clients of the same system; always verify after writing, whichever client was used.
- Embedded rich content (a smart-link or special reference) can corrupt to broken text if
  the whole description is rewritten through a generic format conversion — prefer surgical
  edits over full rewrites when embedded rich content is present.
- There may be no programmatic way to upload an attachment — fall back to telling the human
  to do it manually rather than guessing at an API that doesn't exist.
- Never propose or ask about a state transition beyond the first one (e.g. todo → in
  progress). The rest of the lifecycle is the human's decision alone.

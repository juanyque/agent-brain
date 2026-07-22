# Issue working-doc rules

Use this rule whenever an agent begins implementation work on a tracker ticket (Jira / GitHub issue / equivalent). The artefact this rule produces is a **live working document** kept in sync with the work in progress — not a post-hoc consolidation summary.

## Why this exists

Conversation transcripts and Claude Code windows are ephemeral: scroll-back is finite, sessions die, and re-reads of long planning threads are expensive. A persistent working doc gives the user:

- A **supervision artefact** — they can `git diff` the file to inspect what was planned, what was decided, and what changed, without re-reading the conversation.
- A **recovery anchor** — if a session crashes or the window scrolls past, the working doc captures the current state of agent thinking on this ticket.
- A **single in-progress source of truth** for the ticket, distinct from Jira (intent) and the PR (final implementation).

This is explicitly **not**:
- A consolidation document built at session close.
- A duplicate of the Jira description.
- A duplicate of the daily note's per-project entry (the daily captures the journey across all projects on a given day; the issue doc captures the journey of a single ticket across all the days it lives).

## Source of truth

This file is the canonical procedure. The shape of the document itself lives in `TEMPLATES/TEMPLATE.issue.common.md` (and the brain-local `TEMPLATES/Issue Template.md` wrapper). Do not redefine the document shape here.

## Trigger

Fire the rule the moment the agent identifies that **implementation work on a specific ticket is starting**, regardless of how the signal arrives. The trigger is intent-based, not surface-based.

Examples of signals that fire the rule:

- An explicit slash command for implementation (`/card-engineer:implement-ticket PROJ-313`, `/implement TICKET-123`, equivalents).
- A natural-language request that names a ticket (`"implementa PROJ-313"`, `"vamos a por ABC-456"`, `"abordemos #789"`, `"empezamos con MONEY-42"`).
- Resumption of an in-progress ticket session whose working doc does not yet exist (the prior session ran without this rule).
- Any other unambiguous signal mapping to "now we're starting to ship this ticket".

The trigger is the **intent**, not the cue. If the user says "implementa el ticket que vimos ayer" and the ticket id is clear from context, that fires the rule.

Do **not** fire the rule on:
- PR review of someone else's ticket (their docs are their concern).
- Quick boy-scout fixes that do not have a ticket.
- Spike / research / planning sessions without a committed scope.
- Ticket lookups, status checks, or read-only discussion.

## Behavior at trigger time (create the doc)

1. Resolve the ticket: fetch its tracker entry (Jira description / GitHub issue body / etc.). Capture summary + URL.
2. Resolve the destination path (see "Paths" below).
3. Resolve the short title (see "Short title" below).
4. If the doc does not exist, create the folder + file from `TEMPLATES/Issue Template.md`.
5. Pre-fill the frontmatter (`issue_id`, `project`, `url`, `status: in-progress`, `created_at: YYYY-MM-DD`).
6. Pre-fill `## Context` from the tracker entry. Other sections stay empty — they will be appended to as the work progresses.
7. Announce to the user: `Working doc created at <path>. I'll keep it updated as we go.`

If the doc already exists (resumed session, prior visit), do not overwrite — proceed to the update phase.

## Behavior during work (update the doc)

Update the doc **at the moment** the relevant signal happens, not at session close. Update events:

| Signal | Append to | Format |
|---|---|---|
| Plan agreed (user approves the proposed plan, e.g. via `AskUserQuestion` or explicit yes) | `## Plan` | Dated bullet block with the **plan as agreed**, not the agent's draft. |
| Decision committed (any not-obvious choice the agent or user makes — error-class selection, branch strategy, scope cut, `--no-verify` use, etc.) | `## Decisions` | `D<n> (YYYY-MM-DD) — <decision>. Rationale: <why>.` |
| Analysis done that informed a decision (grep, file read, dependency check, verified non-overlap, etc.) | `## Analysis` | Short dated bullet stating what was checked and what was found. |
| Status change worth recording (PR drafted, CI green, blocked on X, ticket-scope reduced, etc.) | `## Status` | `## YYYY-MM-DD — <short outcome>` sub-heading + 1–3 lines of detail. |
| Blocker or open question surfaced and not yet resolved | `## Status` or a new sub-heading inside Status | Mark explicitly as `Blocker:` or `Open question:` so it's grep-able. |
| Reference newly discovered (related ticket, PR, doc, memory file) | `## References` | One bullet per reference, link-form. |
| Acceptance-criteria progress (a box ticked, a new criterion added) | `## Acceptance criteria` | Tick checkboxes; do not rewrite the list each time. |
| **Demo-worthy result** — a "wow" worth showing later: green end-to-end run, revealing trace, before/after, query with real numbers, elegant diff, a notable visual UI state | sibling **`<slug>.demo-evidence.md`** (NOT a section of the issue doc) | One short entry per the demo-evidence format below. Capture in the moment, same cadence as the rows above. When the evidence is **visual**, ASK the user to take the screenshot with the exact framing — the agent cannot screenshot the user's screen. |

### Demo evidence (sibling facet)

Demo-worthy moments are easy to lose: by the time a demo/1:1/sprint-review is prepared, the green run has scrolled away and the "wow" is gone. Capture them as they happen, in a **sibling facet file** next to the issue doc:

```
<ticket-folder>/<slug>.demo-evidence.md
```

It is a sibling facet (alongside `<slug>.plan.` / `.decisiones.` / `.analisis.` / `.estado.`), consumable by a demo-generation skill (`activity-demo` → `create-slides`). It is **not** a section of the issue working doc — keep supervision (issue doc) separate from demo material (this file), and keep it out of the daily note.

Entry format (one block per piece of evidence):

```
### <hook — one line: the "wow", and for whom>
- Type: trace | screenshot | query | monitoring snapshot | snippet | before/after | metric
- Artifact: <formatted block | image link | query + result + dashboard link | file:line>
- Context: <1–2 lines: why it matters, what it proves in the demo>
- <date> · <TICKET-ID>
```

Heavy binaries (screenshots, evidence files) follow the standard heavy-assets rule: park in `ATTACHMENTS/` temporarily, migrate to online storage, and **link** from the doc — never inline the binary. When a demo-worthy moment is visual, the agent should proactively ask the user for the screenshot rather than skip it.

### Append-mostly format

The doc is structured so a `git diff` between two commits reads as a series of additions, not rewrites:

- New bullets go **at the bottom of the relevant section**, with a date when the date matters.
- Existing entries are **not edited** unless a recorded fact turns out to be wrong (in which case correct in place and note the correction with `(corrected YYYY-MM-DD)`).
- `## Status` may be rewritten as a whole only when summarising — its sub-headings preserve history.
- `## Plan` is allowed one full rewrite if the plan changes substantively mid-flight; the old plan moves to a `## Plan (superseded YYYY-MM-DD)` sub-heading rather than being deleted.

### Cadence

- Update at the **moment** of the signal, not in batches. The supervision value depends on the doc reflecting current state.
- One small targeted edit per signal is preferred over one large edit at session close.
- If multiple signals fire in rapid succession (e.g. user approves plan and immediately answers a clarifying question), batch them into one edit — but do not defer them beyond that.

## Paths

The destination path is derived from cwd + tracker, not from session label:

- `<project-area>` — the project umbrella the work belongs to. Map cwd → known area (e.g. `~/workspace/example-org/demo-app/` → `Example Payments`). If unknown, ask the user.
- `<repo>` — repo or sub-system the work touches (e.g. `Demo App`, `team-tools`, `org-marketplace`). Match the existing `WIP/<project-area>/<repo>/` convention.
- `<ticket-folder>` — folder named `<TICKET-ID> - <Short title>/`. Folder default (not flat file) — even if the ticket has no attachments yet, the folder is a stable container for later supporting artefacts.
- File inside: `<TICKET-ID> - <Short title>.md`.

Full path during active work:

```
WIP/<project-area>/<repo>/<TICKET-ID> - <Short title>/<TICKET-ID> - <Short title>.md
```

## Short title

Derive `<Short title>` deterministically from the tracker summary:

1. Drop tracker-internal prefixes like `[CS]`, `[Platform]`, etc.
2. Drop trailing noise words (`error`, `issue`, `bug` if redundant).
3. Keep natural English capitalization. No kebab-case (this is for humans, not URLs).
4. Cap at ~60 chars for path sanity.

Examples:

- Jira: `[CS] Align RefundHandler missing-processorEventId error to DataIntegrity` → `Align RefundHandler missing-processorEventId to DataIntegrity`
- Jira: `[CS] gRPC layer + handler module consistency cleanup sweep` → `gRPC layer + handler module consistency cleanup sweep`

If the derived title would collide with another folder under the same `<repo>`, append `(v2)` or similar disambiguator.

## Lifecycle: WIP → MEMORY

When the ticket reaches a terminal state (PR merged / ticket closed / cancelled), move the folder via `git mv`:

```
WIP/<project-area>/<repo>/<TICKET-ID> - <Short title>/
  → MEMORY/Projects/<project-area>/<repo>/<TICKET-ID> - <Short title>/
```

Before moving:

- Update frontmatter (`status: merged`, `merged_at: YYYY-MM-DD`; `deployed_at` later if relevant).
- Add a final `## Status` sub-heading capturing the close state (merge commit / Jira state / cleanup done).
- Remove the `wip` tag from frontmatter.

The move is part of the session consolidation flow (see `RULES-SESSION-LIFECYCLE.common.md` → consolidation rules). It is not separate work.

## Interaction with daily notes and session notes

The three artefacts are complementary, not overlapping:

| Artefact | Axis | Lifetime |
|---|---|---|
| Daily note | What happened on day N across all projects | One day |
| Session note | What this specific session is currently doing | One session (handoff or close) |
| **Issue working doc** | What we've been doing on this specific ticket across all its days and sessions | The ticket's full lifetime |

If a ticket spans 3 sessions over 2 days, the issue doc accumulates entries from all three; the dailies each carry their day's slice; the session notes are ephemeral handoff artefacts.

Do not duplicate content across the three. Cross-link instead:

- Daily entry under `[[WORK]]` → `[[<project-area>]]` mentions the ticket and links to the issue doc.
- Session note "Current objective" points at the issue doc as the durable home.
- Issue doc references back to relevant daily entries and session ids only when historical context matters.

## No-trigger checklist

Before firing the rule, confirm:

- Is there an actual ticket id? (no id → no rule)
- Are we the author of the work? (PR review of someone else's ticket → no rule)
- Is the scope committed? (open-ended exploration → no rule until scope crystallises and the user signals "implementemos esto")

If any check fails, do not create the doc. The rule has a strong **default-off**: spurious docs for non-implementation work pollute WIP without serving the supervision purpose.

## How to verify

- Trigger the rule from any signal listed under "Trigger". The doc should appear at the predicted path within one tool call.
- `git diff HEAD~1` on the working doc should be readable as a coherent narrative of the ticket's progression.
- After PR merge, the doc should live under `MEMORY/Projects/...` with terminal-state frontmatter.
- Resuming a ticket session whose doc already exists should NOT overwrite it.

# JOBS.common.md

This file defines the structure and generic tasks for recurring brain maintenance routines.
Execution state is recorded in the local `JOBS_LOGS.md`, not here.

## `JOBS_LOGS.md` format

`JOBS_LOGS.md` is local execution state, but it should use a predictable Markdown format so maintenance tools can parse it.

Retention policy: keep a small rolling history per job, normally the latest 5 entries and at most 10 entries unless there is a clear reason to keep more context. Older details should be consolidated into the relevant daily note, WIP note, or `MEMORY/` note before trimming.

Ordering policy: entries inside each job section should be reverse chronological, with the newest execution first. This keeps the human-readable latest state near the top while preserving a short local history.

Each job section must be a `##` heading with the same name used in this file. Each execution entry should use this shape:

```markdown
## Weekly
- run: 2026-05-17
  run_at: 2026-05-17T01:20:00+02:00
  period: 2026-W20
  status: done
  summary: Reviewed stale sessions and attachment audit; no moves applied.
  refs: [[2026-05-17]], [[Estandarización del brain]]
```

Required fields:

- `run`: date when the maintenance review/execution happened, as `YYYY-MM-DD`.
- `period`: scheduling period covered by the entry:
  - Daily and Session consolidation: `YYYY-MM-DD`.
  - Weekly: ISO week `YYYY-Www`, for example `2026-W20`.
  - Monthly: `YYYY-MM`.
  - Yearly: `YYYY`.
- `status`: `done`, `in_progress`, `partial`, or `skipped`.
- `summary`: one-line durable summary of the result.

Optional fields:

- `refs`: links to relevant daily notes, WIP notes, reports, or session notes.
- `next`: next follow-up if the job was `in_progress` or `partial`.
- `run_at`: exact local execution timestamp as ISO 8601, for example `2026-05-17T01:20:00+02:00`. Use this when known, especially when several entries share the same `run` date.

`maintenance_scheduler.py` reads `run`, `period`, and `status`, and uses `run_at` when present to choose/report the latest entry more precisely. Free-form prose may be useful to humans, but it should not be the only execution state for new entries.

`JOBS_LOGS.md` should contain execution state only. Do not repeat these format or retention rules in local brain logs; local logs should just follow them.

### Status hygiene

Calendar-driven jobs (Weekly, Monthly, Yearly) should not remain `in_progress` as a standing state. If a routine review exposes larger cleanup work, close the entry as `done`, `partial`, or `skipped` with a clear summary, then track the actual follow-up in WIP or the standardization process note. This keeps `JOBS_LOGS.md` reflecting routine cadence, not unresolved project work.

## Structure convention

Each job section follows this shape:

- `### Purpose` — what this routine does.
- `### Trigger` — required only for **event-driven** jobs (Daily, Session consolidation): user phrases like "nuevo día" / "nueva sesión" or explicit context changes that an agent intercepts in real time.
- `### Schedule` — required only for **calendar-driven** jobs (Weekly, Monthly, Yearly): the period key used by `maintenance_scheduler.py`.
- `### Links` — where the procedure lives. Jobs link to owner rules and task types; they do not duplicate flow checklists or detailed maintenance procedures.
- Execution logs go in `JOBS_LOGS.md`, not in this file.

**Calendar-driven jobs** (Weekly, Monthly, Yearly) do not declare a `### Trigger`. Their scheduling is derived from the `period` field in `JOBS_LOGS.md` and surfaced by `maintenance_scheduler.py`, which decides whether a job is due based on the latest entry. A user phrase such as "weekly maintenance" can always force one of them to run, but that is an override rather than the primary trigger.

## Ownership metadata

| Policy area | Owner | Authority |
|---|---|---|
| job-shape | JOBS.common.md | purpose-trigger-schedule-links-only |
| procedure-source | RULES-SESSION-LIFECYCLE.common.md | linked-not-duplicated |
| daily-semantics-source | RULES-DAILY-NOTES.common.md | linked-not-duplicated |
| git-operations | user | explicit-authorization-required |

## Daily (Day change)

### Purpose
- Handle the transition from one day to the next within an ongoing session.
- This is NOT the same as closing a session. The session stays open.
- Procedure source of truth: `RULES-SESSION-LIFECYCLE.md` → Flow 1.

### Trigger
- User says "nuevo día", "new day", "cambio de día", "cambia de día", "we changed day", or similar indicating day rollover.

### Links
- Procedure source of truth: `RULES-SESSION-LIFECYCLE.md` → Flow 1.
- Daily semantics source of truth: `RULES-DAILY-NOTES.md` → Objectives review and cleanup timing.

## Session consolidation

### Purpose
- Consolidate one or more working sessions into the brain when starting a new session.
- Procedure source of truth: `RULES-SESSION-LIFECYCLE.md` → Flow 2.

### Trigger
- User says "nueva sesión", "new session", "inicio sesión", or starts a clearly new session context.

### Links
- Procedure source of truth: `RULES-SESSION-LIFECYCLE.md` → Flow 2.
- Daily semantics source of truth: `RULES-DAILY-NOTES.md` → Objectives review and cleanup timing.
- Stale-session follow-up semantics: `RULES-SESSION-LIFECYCLE.md` → Previous sessions rollover.

## Weekly

### Purpose
- Hold recurring weekly maintenance routines for the brain.

### Schedule
- Period: `YYYY-Www`.

### Links
- Session cleanup and WIP review semantics: `RULES-SESSION-LIFECYCLE.md` → Previous sessions rollover, Closing gate, and Recurring session and WIP review.
- Attachment review semantics: `RULES-ATTACHMENTS.md`.
- Trash review semantics: `brain-maintenance.md` → Recurring maintenance reviews.
- Basename collision procedure: `TASK_TYPES/basename-collision-cleanup.md`.

## Monthly

### Purpose
- Hold recurring monthly maintenance routines for the brain.

### Schedule
- Period: `YYYY-MM`.

### Links
- WIP and MEMORY semantics: `BRAIN.md`.
- Review report lifecycle: `RULES-REVIEW-EVIDENCE.md`.
- Attachment handling semantics: `RULES-ATTACHMENTS.md`.
- Maintenance-rule refinement: `brain-maintenance.md` → Recurring maintenance reviews.
- Git operations remain user-authorized only; this job may identify candidates but does not authorize moves.

## Yearly

### Purpose
- Hold recurring yearly maintenance routines for the brain.

### Schedule
- Period: `YYYY`.

### Links
- Journal structure and classification: `RULES-DAILY-NOTES.md` → Journal archive and classification.
- Daily-note semantics: `RULES-DAILY-NOTES.md`.
- File movement rules: `RULES-FILE-NAMING.md`.

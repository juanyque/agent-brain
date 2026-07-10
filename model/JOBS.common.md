# JOBS.common.md

This file defines the structure and generic tasks for recurring vault maintenance routines.
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
  refs: [[2026-05-17]], [[Estandarización del vault]]
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

`JOBS_LOGS.md` should contain execution state only. Do not repeat these format or retention rules in local vault logs; local logs should just follow them.

### Status hygiene

Calendar-driven jobs (Weekly, Monthly, Yearly) should not remain `in_progress` as a standing state. If a routine review exposes larger cleanup work, close the entry as `done`, `partial`, or `skipped` with a clear summary, then track the actual follow-up in WIP or the standardization process note. This keeps `JOBS_LOGS.md` reflecting routine cadence, not unresolved project work.

## Structure convention

Each job section follows this shape:

- `### Purpose` — what this routine does.
- `### Trigger` — required only for **event-driven** jobs (Daily, Session consolidation): user phrases like "nuevo día" / "nueva sesión" or explicit context changes that an agent intercepts in real time.
- `### Tasks` — what to do. Generic tasks are defined here; local wrappers may add vault-specific tasks.
- Execution logs go in `JOBS_LOGS.md`, not in this file.

**Calendar-driven jobs** (Weekly, Monthly, Yearly) do not declare a `### Trigger`. Their scheduling is derived from the `period` field in `JOBS_LOGS.md` and surfaced by `maintenance_scheduler.py`, which decides whether a job is due based on the latest entry. A user phrase such as "weekly maintenance" can always force one of them to run, but that is an override rather than the primary trigger.

## Daily (Day change)

### Purpose
- Handle the transition from one day to the next within an ongoing session.
- This is NOT the same as closing a session. The session stays open.
- Procedure source of truth: `RULES-SESSION-LIFECYCLE.md` → Flow 1.

### Trigger
- User says "nuevo día", "new day", "cambio de día", "cambia de día", "we changed day", or similar indicating day rollover.

### Tasks
- Run the Flow 1 checklist in `RULES-SESSION-LIFECYCLE.md`.
- Run the Objectives review pass for the closing day (`RULES-DAILY-NOTES.md` → Objectives review) before the empty-category cleanup.

## Session consolidation

### Purpose
- Consolidate one or more working sessions into the vault when starting a new session.
- Procedure source of truth: `RULES-SESSION-LIFECYCLE.md` → Flow 2.

### Trigger
- User says "nueva sesión", "new session", "inicio sesión", or starts a clearly new session context.

### Tasks
- Run the Flow 2 checklist in `RULES-SESSION-LIFECYCLE.md`.
- Run the Objectives review pass for the day being consolidated (`RULES-DAILY-NOTES.md` → Objectives review) before any empty-category cleanup.
- Record stale-session follow-up items only if they require later maintenance.

## Weekly

### Purpose
- Hold recurring weekly maintenance routines for the vault.

### Tasks
- Review orphaned or stale session notes that were not fully consolidated.
- Review blocked or stale WIP items and decide whether they should remain in active WIP.
- Run attachment-maintenance review: detect possible orphaned attachments, misplaced attachments, and conflict cases without deleting anything automatically; move suspected orphaned attachments to `QUARANTINE/ATTACHMENTS/` for review.
- Review `QUARANTINE/TRASH/` for notes older than 15 days and propose candidates for permanent deletion. Do not delete automatically; list candidates and wait for explicit human approval.
- Run the basename-collision detector to catch new duplicates created during the week: `_COMMON/SKILLS/obsidian/scripts/check_basename_collisions.py --vault-root <vault> --exclude-path <runtime-governed paths> [--apply]`. Read-only by default; `--apply` auto-renames files no reference points at (per-file safety). Interactive review of `(needs edits)` groups follows the procedure in `TASK_TYPES/basename-collision-cleanup.md` (wrapper to the common task-type guide).

## Monthly

### Purpose
- Hold recurring monthly maintenance routines for the vault.

### Tasks
- Review whether WIP items should be consolidated into MEMORY, moved to BACKLOG, or archived to ARCHIVED (for historically important but no longer active content).
- Review aged review reports in `WIP/` (brag, feedback, complaint reports whose cycle has closed): propose moving them to `ARCHIVED/Reviews/` via `git mv`. Do not move reports tagged `sensitive` without explicit confirmation. Evidence notes in `WIP/evidence/` are permanent and never proposed for archival.
- Review ARCHIVED contents for stale references or dead links; note findings but do not delete content automatically.
- Review recurring maintenance rules and refine them if they are creating unnecessary friction.
- Review whether attachment-handling rules or scripts need refinement based on real conflict cases.

## Yearly

### Purpose
- Hold recurring yearly maintenance routines for the vault.

### Tasks
- Move closed-year daily notes into `JOURNAL/<year>/` while keeping the current year directly under `JOURNAL/`.
- Review whether non-daily notes still remain in `JOURNAL/` and classify them.

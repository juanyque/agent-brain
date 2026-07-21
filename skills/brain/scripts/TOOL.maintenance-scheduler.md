# maintenance_scheduler.py

## Purpose
- Decide which recurring vault maintenance jobs are due before running structural standardization assessment.
- Use local `JOBS_LOGS.md` execution state plus current date and daily-note state.

## Scope
- Daily (Day change)
- Session consolidation
- Weekly
- Monthly
- Yearly

## Decision model
- `due`: the routine appears due and should be proposed to the user.
- `review`: the routine is event-triggered, in progress, or lacks enough state for an automatic not-due decision.
- `not_due`: the routine appears already handled for the relevant period.

## Usage

### Human-readable report
```bash
python3 ~/.agents/skills/brain/scripts/maintenance_scheduler.py --brain-root .
```

### Machine-readable report
```bash
python3 ~/.agents/skills/brain/scripts/maintenance_scheduler.py --brain-root . --json
```

### Test with a fixed date
```bash
python3 ~/.agents/skills/brain/scripts/maintenance_scheduler.py --brain-root . --date 2026-05-16
```

## Safety model
- Read-only.
- Does not edit `JOBS_LOGS.md`.
- Does not execute maintenance tasks automatically.
- The agent presents due/review tasks to the user before doing any routine.

## `JOBS_LOGS.md` parsing contract
- Preferred entries use the format documented in `JOBS.md`: `run`, `period`, `status`, `summary`, plus optional `run_at`, `refs`, and `next`.
- The scheduler reads `run`, `period`, and `status` from each job section, and uses optional `run_at` to choose/report the latest same-day entry more precisely.
- It still tolerates older free-form entries by scanning for dates, but new entries should be structured.
- Keep a small rolling history per job: normally 5 entries and at most 10 unless extra context is intentionally preserved elsewhere.
- Keep newest entries first inside each job section.

## Known limitations
- It does not trim old entries automatically.
- Session consolidation is event-triggered, so it is reported as `review` rather than fully automatic.

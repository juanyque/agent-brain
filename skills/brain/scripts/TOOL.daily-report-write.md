# Daily report writer

`daily_report_write.py` stores the `brain daily` report in today's daily note. It is the write step
that follows `daily_report_collect.py` once the user has approved the report.

```bash
python3 ~/.agents/skills/brain/scripts/daily_report_write.py \
  --brain-root "<brain>" \
  --report-file /path/to/report.md \
  --range YYYY-MM-DD..YYYY-MM-DD \
  [--apply]
```

Dry-run by default: it prints the planned action and writes nothing. `--apply` writes the note, reads
it back to verify, and writes the latest-run log (`--log-path` overrides its location). It uses
Python's standard library.

## What it does

- Writes only today's daily note. `--date` exists but must equal today; any other day is refused.
- Never creates the daily. When today's note is missing it stops and points to the session-open rollover.
- Wraps the report in `<!-- daily-report range=A..B -->` and `<!-- /daily-report -->` inside the
  `# Daily report` section, so a later run replaces the report. Running it again with the same input
  leaves the note unchanged.
- Actions, reported as `action:`:
  - `fill-empty-section` — the section exists and is blank (the template shape).
  - `insert-section` — the note lacks the section; it is added before `# Actions` (or at the end when
    the note has no `# Actions`).
  - `replace-report` — a previous report exists; only the content between the markers changes.
- Opens the note without following symlinks, like the session-open tools.
- Prints `warning:` (and still writes) when the report has no `## ` section heading, which usually
  means the section titles were written as bold text.

## Refusals (exit code 2, nothing written)

- The report is empty, contains a top-level `# ` heading (it would end the `# Daily report`
  section; write sections as `## `), or contains the markers.
- The section already has content that is not a managed report: move it by hand first.
- The markers are unbalanced, duplicated or out of order.
- The range is not `YYYY-MM-DD..YYYY-MM-DD` or ends before it starts.
- The daily is missing, ambiguous, or a symlink.

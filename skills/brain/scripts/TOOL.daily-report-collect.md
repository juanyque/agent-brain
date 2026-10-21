# Daily report collector

`daily_report_collect.py` gathers what happened in a brain over a date range and prints it as JSON.
It is the evidence step of `brain daily`: the calling agent composes the report from this output.

```bash
python3 ~/.agents/skills/brain/scripts/daily_report_collect.py \
  --brain-root "<brain>" \
  [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--scan-dir <dir>]
```

The tool is read-only and uses Python's standard library. It never writes a log or touches the brain.

## Range

- `--from` defaults to the latest daily note dated before today. Pass it to widen the range, for
  example the previous Friday when reporting on a Monday.
- `--to` defaults to today. Both ends are inclusive.
- `--today` overrides the current date (used by tests).
- An error (exit code 2) is returned when `--from` is after `--to`, when no daily precedes today and
  `--from` was not given, or when the journal configuration is invalid.

## Output

| Key | Content |
|---|---|
| `range` | `from`, `to`, `today` |
| `days` | One entry per existing daily in range: its registered `sessions` and the raw `work` lines of `* [[WORK]]:` |
| `missing_dailies` | The `--from` day when it has no daily note |
| `sessions` | Session notes registered in a daily of the range, plus unregistered notes created or modified in range. Each has `status`, `empty`, `objective`, `next_step`, `open_questions`, `modified`, `registered_in` and `reason` |
| `issues` | Issue notes (frontmatter `issue_id`) touched in range (a dated entry or a modification date in range), with `status`, `work_type`, `url`, `summary`, `dated_entries` and `status_section`. Untouched issue notes are not listed here |
| `referenced_issues` | Existing issue notes that an in-range generated file references but that were not touched in range: `issue_id`, `path`, `work_type`, `status`. Context only, never activity |
| `generated_files` | Files under `OUTBOX/` (plus any `--scan-dir`) modified in range, listed once even when scan dirs overlap, with `referenced_by` (sorted issue ids) |
| `warnings` | Registered sessions whose note could not be found, and issue ids whose primary notes disagree on `work_type` or `status` |

## Attribution rules

- **A session note's file date is its creation day, not its activity day.** Activity is attributed
  through the daily notes' `# Sessions` registrations and the note's modification date.
- **Issue activity is attributed by dated headings.** Any heading of level 2 to 4 that starts with
  `YYYY-MM-DD` (for example `### 2026-03-09: outcome`) is an entry for that day, with its body. An issue
  note modified in range but without dated entries is still returned, with its `status_section`.
- **Facet files** (`<id>.analysis.md`, evidence, drafts) that share an `issue_id` with a primary
  `folder/folder.md` note are listed in that note's `facets`.
- `work_type` is returned verbatim. An empty value means the user has not answered it yet; the report
  must ask instead of guessing.
- **Generated files are attributed against every issue note**, touched or not, together with its facets.
  A note references a file when its text names the file's path or one of its folders as a whole
  path (`OUTBOX/run-1/out.log` or `OUTBOX/run-1`, also as a wiki link, a Markdown link target, in
  angle brackets, or with `%20` for spaces). `OUTBOX/run-1` never matches `OUTBOX/run-1-old`, a bare
  file name is never enough, and the scan folder itself (`OUTBOX`) proves nothing. Shorthand
  references stay unattributed.
- A `generated_files` entry with an empty `referenced_by` has no matching reference in any issue
  note. Report it as unattributed; that does not prove that no issue note exists.
- Modification dates come from the filesystem and can be reset by a checkout, so treat them as a
  hint, never as proof of when work happened.

#!/usr/bin/env python3
"""Store the `brain daily` report in today's daily note, between replaceable markers.

Dry-run by default; pass `--apply` to write. The report goes into the `# Daily report`
section (created before `# Actions` when the note lacks it) wrapped in
`<!-- daily-report range=A..B -->` / `<!-- /daily-report -->`, so running it again with
another range replaces the previous report. Only today's note is ever written.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import Reporter, build_command_string  # noqa: E402
from session_open_discovery import JournalConfigError, list_daily_notes, load_journal_folder  # noqa: E402
from session_open_fs import (  # noqa: E402
    UnsafeDailyPathError,
    _read_daily_text,
    _safe_write_scope,
    _write_text,
)

HEADING = "# Daily report"
END_MARKER = "<!-- /daily-report -->"
START_RE = re.compile(r"^<!-- daily-report range=(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2}) -->$")
RANGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")
DEFAULT_LOG = Path(__file__).resolve().with_name("daily_report_write.log")


def start_marker(range_label: str) -> str:
    return f"<!-- daily-report range={range_label} -->"


def validate_report(report: str) -> str:
    body = report.strip("\n").rstrip()
    if not body.strip():
        raise ValueError("the report is empty")
    for line in body.splitlines():
        if line.startswith("# "):
            raise ValueError(
                "the report must not contain top-level `# ` headings (they would end the "
                f"`{HEADING}` section); use `## ` or deeper: {line!r}"
            )
        if "<!-- daily-report" in line or END_MARKER in line:
            raise ValueError("the report must not contain daily-report markers")
    return body


def report_warnings(report: str) -> list[str]:
    """Non-blocking advice about the report body (validate_report already refused the unsafe cases)."""
    if not any(line.startswith("## ") for line in report.splitlines()):
        return ["the report has no `## ` section heading; sections should be `## ` headings, not bold text"]
    return []


def validate_range(range_label: str) -> str:
    match = RANGE_RE.match(range_label)
    if not match:
        raise ValueError(f"--range must look like YYYY-MM-DD..YYYY-MM-DD, got {range_label!r}")
    first, last = (date.fromisoformat(part) for part in match.groups())
    if first > last:
        raise ValueError(f"--range starts after it ends: {range_label}")
    return range_label


def render(text: str, report: str, range_label: str) -> tuple[str, str]:
    """Return (new_text, action). Raises ValueError when the note cannot be updated safely."""
    body = validate_report(report)
    block = [start_marker(range_label), *body.splitlines(), END_MARKER]
    lines = text.splitlines()

    starts = [i for i, line in enumerate(lines) if START_RE.match(line)]
    ends = [i for i, line in enumerate(lines) if line == END_MARKER]
    if len(starts) != len(ends) or len(starts) > 1:
        raise ValueError(
            f"malformed daily-report markers ({len(starts)} start, {len(ends)} end); fix the note by hand"
        )
    trailing = "\n" if text.endswith("\n") or not text else ""

    if starts:
        if ends[0] < starts[0]:
            raise ValueError("daily-report end marker comes before its start marker")
        return "\n".join(lines[: starts[0]] + block + lines[ends[0] + 1 :]) + trailing, "replace-report"

    headings = [i for i, line in enumerate(lines) if line == HEADING]
    if len(headings) > 1:
        raise ValueError(f"the note has {len(headings)} `{HEADING}` sections")
    if headings:
        head = headings[0]
        end = head + 1
        while end < len(lines) and not lines[end].startswith("# "):
            end += 1
        if any(line.strip() for line in lines[head + 1 : end]):
            raise ValueError(
                f"`{HEADING}` already has content that is not a managed report; move it by hand first"
            )
        rest = lines[end:]
        new = lines[: head + 1] + [""] + block + ([""] if rest else []) + rest
        return "\n".join(new) + trailing, "fill-empty-section"

    actions = next((i for i, line in enumerate(lines) if line.startswith("# Actions")), None)
    section = [HEADING, "", *block]
    if actions is None:
        new = lines + ([""] if lines and lines[-1].strip() else []) + section
    else:
        new = lines[:actions] + section + [""] + lines[actions:]
    return "\n".join(new) + "\n", "insert-section"


def find_daily(brain_root: Path, day: date) -> Path:
    journal_root = brain_root / load_journal_folder(brain_root)
    matches = [path for path in list_daily_notes(journal_root) if path.stem == day.isoformat()]
    if not matches:
        raise ValueError(
            f"no daily note for {day.isoformat()}; run the session-open rollover first (this tool never creates it)"
        )
    if len(matches) > 1:
        raise ValueError(f"several daily notes match {day.isoformat()}: {', '.join(map(str, matches))}")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brain-root", required=True, type=Path)
    parser.add_argument("--report-file", required=True, type=Path, help="Markdown report body, without markers")
    parser.add_argument("--range", dest="range_label", required=True, help="YYYY-MM-DD..YYYY-MM-DD covered by the report")
    parser.add_argument("--date", help="daily note to write, YYYY-MM-DD; must be today (default)")
    parser.add_argument("--today", help="override today's date, YYYY-MM-DD (tests)")
    parser.add_argument("--apply", action="store_true", help="write the note (default: dry-run)")
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG, help="latest-run log (apply mode only)")
    args = parser.parse_args(argv)

    reporter = Reporter(args.log_path)
    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
        day = date.fromisoformat(args.date) if args.date else today
        if day != today:
            raise ValueError(f"refusing to write the report into {day.isoformat()}: only today's note ({today.isoformat()}) is written")
        range_label = validate_range(args.range_label)
        brain_root = args.brain_root.resolve()
        note = find_daily(brain_root, day)
        report = args.report_file.read_text(encoding="utf-8")
        before = _read_daily_text(note, brain_root)
        after, action = render(before, report, range_label)
    except (ValueError, OSError, JournalConfigError, UnsafeDailyPathError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    reporter.write("# Daily report writer")
    reporter.write(f"mode: {'apply' if args.apply else 'dry-run'}")
    reporter.write(f"command: {build_command_string()}")
    reporter.write(f"note: {note.relative_to(brain_root).as_posix()}")
    reporter.write(f"range: {range_label}")
    reporter.write(f"action: {action}")
    reporter.write(f"lines: {len(before.splitlines())} -> {len(after.splitlines())}")
    for warning in report_warnings(report):
        reporter.write(f"warning: {warning}")
    if not args.apply:
        reporter.write("dry-run: nothing written; pass --apply to write")
        return 0

    try:
        with _safe_write_scope(brain_root):
            _write_text(note, after)
        verified = _read_daily_text(note, brain_root)
    except (OSError, UnsafeDailyPathError) as exc:
        print(f"ERROR: write failed: {exc}", file=sys.stderr)
        return 1
    if verified != after:
        print("ERROR: the note does not match what was written", file=sys.stderr)
        return 1
    reporter.write("written and verified")
    reporter.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

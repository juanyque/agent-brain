#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
WEEK_RE = re.compile(r"\b(\d{4}-W\d{2})\b")
YEAR_RE = re.compile(r"^\s*-\s*(\d{4})\b")
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
ENTRY_START_RE = re.compile(r"^\s*-\s+run:\s*(\d{4}-\d{2}-\d{2})\s*$")
ENTRY_FIELD_RE = re.compile(r"^\s{2,}([a-z_]+):\s*(.*?)\s*$")

JOB_NAMES = ["Daily (Day change)", "Session consolidation", "Weekly", "Monthly", "Yearly"]


@dataclass
class JobDecision:
    name: str
    status: str
    reason: str
    last_run: str
    recommendation: str


@dataclass
class JobLogEntry:
    run: date
    period: str
    status: str
    summary: str
    run_at: datetime | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Decide which recurring vault maintenance jobs are due.")
    parser.add_argument("--brain-root", default=".", help="Vault root path")
    parser.add_argument("--date", help="Override today's date as YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser.parse_args()


from _common import build_command_string  # noqa: E402  (lives next to this script)


def read_sections(path: Path) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    if not path.exists():
        return sections
    current = "_preamble"
    for line in path.read_text(encoding="utf-8").splitlines():
        match = SECTION_RE.match(line)
        if match:
            current = match.group(1)
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def latest_date(lines: list[str]) -> date | None:
    dates: list[date] = []
    for line in lines:
        for raw in DATE_RE.findall(line):
            try:
                dates.append(date.fromisoformat(raw))
            except ValueError:
                continue
    return max(dates) if dates else None


def parse_job_entries(lines: list[str]) -> list[JobLogEntry]:
    entries: list[JobLogEntry] = []
    current: dict[str, str] | None = None
    for line in lines:
        start = ENTRY_START_RE.match(line)
        if start:
            if current is not None:
                entry = build_job_entry(current)
                if entry is not None:
                    entries.append(entry)
            current = {"run": start.group(1)}
            continue
        if current is None:
            continue
        field = ENTRY_FIELD_RE.match(line)
        if field:
            current[field.group(1)] = field.group(2)
    if current is not None:
        entry = build_job_entry(current)
        if entry is not None:
            entries.append(entry)
    return entries


def build_job_entry(raw: dict[str, str]) -> JobLogEntry | None:
    try:
        run = date.fromisoformat(raw["run"])
    except (KeyError, ValueError):
        return None
    return JobLogEntry(
        run=run,
        period=raw.get("period", run.isoformat()),
        status=raw.get("status", "done").casefold(),
        summary=raw.get("summary", ""),
        run_at=parse_run_at(raw.get("run_at")),
    )


def parse_run_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def entry_sort_key(entry: JobLogEntry) -> datetime:
    return entry.run_at or datetime.combine(entry.run, datetime.min.time())


def entry_label(entry: JobLogEntry) -> str:
    return entry.run_at.isoformat() if entry.run_at is not None else entry.run.isoformat()


def latest_entry(entries: list[JobLogEntry]) -> JobLogEntry | None:
    return max(entries, key=entry_sort_key) if entries else None


def latest_run(lines: list[str]) -> date | None:
    entry = latest_entry(parse_job_entries(lines))
    if entry is not None:
        return entry.run
    return latest_date(lines)


def latest_run_label(lines: list[str]) -> str:
    entry = latest_entry(parse_job_entries(lines))
    if entry is not None:
        return entry_label(entry)
    latest = latest_date(lines)
    return latest.isoformat() if latest else "none"


def contains_current_week(lines: list[str], today: date) -> bool:
    current = f"{today.isocalendar().year}-W{today.isocalendar().week:02d}"
    entries = parse_job_entries(lines)
    if any(entry.period == current and entry.status == "done" for entry in entries):
        return True
    if any(raw == current for line in lines for raw in WEEK_RE.findall(line)):
        return True
    return any((found := latest_date([line])) is not None and found.isocalendar()[:2] == today.isocalendar()[:2] for line in lines)


def contains_current_month(lines: list[str], today: date) -> bool:
    current = f"{today.year}-{today.month:02d}"
    entries = parse_job_entries(lines)
    if any(entry.period == current and entry.status == "done" for entry in entries):
        return True
    for line in lines:
        for raw in DATE_RE.findall(line):
            try:
                d = date.fromisoformat(raw)
            except ValueError:
                continue
            if d.year == today.year and d.month == today.month:
                return True
    return False


def yearly_state(lines: list[str], today: date) -> tuple[str, str, str]:
    current = str(today.year)
    for entry in parse_job_entries(lines):
        if entry.period != current:
            continue
        if entry.status in {"in_progress", "partial", "pending"}:
            return "in_progress", entry_label(entry), f"{entry.status}: {entry.summary}".strip()
        if entry.status == "done":
            return "done", entry_label(entry), f"done: {entry.summary}".strip()
    for line in lines:
        match = YEAR_RE.match(line)
        if not match or int(match.group(1)) != today.year:
            continue
        lower = line.casefold()
        if "in progress" in lower or "pending" in lower:
            return "in_progress", str(today.year), line.strip("- ").strip()
        return "done", str(today.year), line.strip("- ").strip()
    return "missing", "none", "none"


def daily_note_state(brain_root: Path, today: date) -> tuple[bool, str]:
    config = brain_root / ".obsidian" / "daily-notes.json"
    folder = "JOURNAL"
    if config.exists():
        try:
            folder = json.loads(config.read_text(encoding="utf-8")).get("folder", folder)
        except json.JSONDecodeError:
            pass
    path = brain_root / folder / f"{today.isoformat()}.md"
    return path.exists(), str(path.relative_to(brain_root))


def decide_jobs(brain_root: Path, today: date) -> list[JobDecision]:
    sections = read_sections(brain_root / "JOBS_LOGS.md")
    decisions: list[JobDecision] = []

    daily_lines = sections.get("Daily (Day change)", [])
    daily_latest = latest_run(daily_lines)
    today_daily_exists, today_daily_path = daily_note_state(brain_root, today)
    if daily_latest == today:
        decisions.append(JobDecision("Daily (Day change)", "not_due", "Daily job already logged today.", latest_run_label(daily_lines), "No action needed."))
    elif today_daily_exists:
        decisions.append(JobDecision("Daily (Day change)", "due", f"Today's daily note exists at `{today_daily_path}`, but Daily job is not logged for today.", daily_latest.isoformat() if daily_latest else "none", "Review whether day-change cleanup/session carry-over has been completed; log it if done."))
    else:
        decisions.append(JobDecision("Daily (Day change)", "due", f"Today's daily note is missing at `{today_daily_path}`.", daily_latest.isoformat() if daily_latest else "none", "Run daily/session-start rollover before continuing substantial work."))

    session_lines = sections.get("Session consolidation", [])
    session_latest = latest_run(session_lines)
    if session_latest is None:
        decisions.append(JobDecision("Session consolidation", "review", "No session consolidation execution is recorded.", "none", "Review open session notes and decide whether consolidation is needed."))
    else:
        decisions.append(JobDecision("Session consolidation", "review", "Session consolidation is event-triggered, not calendar-triggered.", latest_run_label(session_lines), "Review only when starting/closing/changing sessions."))

    weekly_lines = sections.get("Weekly", [])
    if contains_current_week(weekly_lines, today):
        decisions.append(JobDecision("Weekly", "not_due", "Weekly job has an entry in the current ISO week.", latest_run_label(weekly_lines), "No action needed."))
    else:
        weekly_latest = latest_run(weekly_lines)
        decisions.append(JobDecision("Weekly", "due", "No Weekly job entry found for the current ISO week.", weekly_latest.isoformat() if weekly_latest else "none", "Propose weekly maintenance checklist."))

    monthly_lines = sections.get("Monthly", [])
    if contains_current_month(monthly_lines, today):
        decisions.append(JobDecision("Monthly", "not_due", "Monthly job has an entry in the current month.", latest_run_label(monthly_lines), "No action needed."))
    else:
        monthly_latest = latest_run(monthly_lines)
        decisions.append(JobDecision("Monthly", "due", "No Monthly job entry found for the current month.", monthly_latest.isoformat() if monthly_latest else "none", "Propose monthly maintenance checklist."))

    yearly_lines = sections.get("Yearly", [])
    year_status, year_last_run, year_detail = yearly_state(yearly_lines, today)
    if year_status == "done":
        decisions.append(JobDecision("Yearly", "not_due", f"Yearly job has an entry for the current year. {year_detail}", year_last_run, "No action needed."))
    elif year_status == "in_progress":
        decisions.append(JobDecision("Yearly", "review", f"Yearly job is marked in progress for the current year. {year_detail}", year_last_run, "Review whether yearly JOURNAL/archive tasks should be completed or explicitly postponed."))
    else:
        decisions.append(JobDecision("Yearly", "due", "No Yearly job entry found for the current year.", "none", "Propose yearly maintenance checklist."))

    return decisions


def render_report(brain_root: Path, today: date, decisions: list[JobDecision]) -> str:
    lines = [
        "# Maintenance scheduler",
        "",
        f"brain_root: {brain_root}",
        f"today: {today.isoformat()}",
        f"command: {build_command_string()}",
        "",
        "## Decisions",
    ]
    for decision in decisions:
        lines.extend([
            f"- {decision.name}",
            f"  status: {decision.status}",
            f"  last_run: {decision.last_run}",
            f"  reason: {decision.reason}",
            f"  recommendation: {decision.recommendation}",
        ])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    brain_root = Path(args.brain_root).expanduser().resolve()
    if not brain_root.is_dir():
        print(f"Vault root not found: {brain_root}")
        return 1
    today = date.fromisoformat(args.date) if args.date else datetime.now().date()
    decisions = decide_jobs(brain_root, today)
    if args.json:
        print(json.dumps([decision.__dict__ for decision in decisions], ensure_ascii=False, indent=2))
    else:
        print(render_report(brain_root, today, decisions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

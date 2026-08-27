#!/usr/bin/env python3
"""Deterministic due-ness decisions for source ingestion.

See RULES-OPTIONAL-CAPABILITIES.common.md -> "Source ingestion". The agent never guesses
whether a source is due for a check; this script decides from each descriptor's
`Last checked:` field and cadence, and the agent only interprets the result (which sources
are due, then whether what a subagent found is worth surfacing).

Whether the capability is activated for the current project at all is an agent-side
decision, made the same way as every other optional capability (WIP/WIP.md must link
`sources.registry.md` under a heading matching the current project) -- this script does
not duplicate that check, matching how Graphify's own activation gate is entirely
agent-prose-driven with no script involved.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


SOURCE_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^-\s+([A-Za-z][A-Za-z0-9 ()]*):\s*(.*?)\s*$")

VALID_STATUS = ("ok", "no_activity", "degraded")


@dataclass
class SourceEntry:
    slug: str
    status: str
    source_type: str
    descriptor: str
    purpose: str


@dataclass
class SourceDecision:
    slug: str
    source_type: str
    due: bool
    reason: str
    last_checked: str
    cadence_days: int


def parse_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in lines:
        match = FIELD_RE.match(line)
        if match:
            fields[match.group(1).strip().casefold()] = match.group(2).strip()
    return fields


def parse_registry_entries(text: str) -> list[SourceEntry]:
    entries: list[SourceEntry] = []
    current_slug: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_slug is None:
            return
        fields = parse_fields(current_lines)
        entries.append(
            SourceEntry(
                slug=current_slug,
                status=fields.get("status", "disabled").casefold(),
                source_type=fields.get("type", ""),
                descriptor=fields.get("descriptor", ""),
                purpose=fields.get("purpose", ""),
            )
        )

    for line in text.splitlines():
        heading = SOURCE_HEADING_RE.match(line)
        if heading:
            flush()
            current_slug = heading.group(1).strip()
            current_lines = []
            continue
        if current_slug is not None:
            current_lines.append(line)
    flush()
    return entries


def enabled_sources(registry_path: Path) -> list[SourceEntry]:
    if not registry_path.exists():
        return []
    text = registry_path.read_text(encoding="utf-8")
    return [entry for entry in parse_registry_entries(text) if entry.status == "enabled"]


def parse_descriptor_schedule(descriptor_path: Path) -> tuple[date | None, int]:
    """Returns (last_checked, cadence_days); last_checked is None when never
    checked. cadence_days is 0 as a sentinel for "always due" (e.g. a
    calendar source, where due-ness isn't about staleness but about the
    source being inherently time-sensitive every session)."""
    if not descriptor_path.exists():
        return None, 1
    fields = parse_fields(descriptor_path.read_text(encoding="utf-8").splitlines())
    cadence_raw = fields.get("check cadence (days)", "1").strip()
    if cadence_raw.casefold() == "always":
        cadence_days = 0
    else:
        try:
            cadence_days = max(1, int(cadence_raw))
        except ValueError:
            cadence_days = 1
    try:
        last_checked = date.fromisoformat(fields.get("last checked", ""))
    except ValueError:
        last_checked = None
    return last_checked, cadence_days


def descriptor_path_for(sources_dir: Path, slug: str) -> Path:
    return sources_dir / f"sources.{slug}.md"


def decide_due(descriptor_path: Path, today: date, slug: str, source_type: str = "") -> SourceDecision:
    last_checked, cadence_days = parse_descriptor_schedule(descriptor_path)
    if cadence_days == 0:
        last_label = last_checked.isoformat() if last_checked else "none"
        return SourceDecision(slug, source_type, True, "always due (cadence: always)", last_label, cadence_days)
    if last_checked is None:
        return SourceDecision(slug, source_type, True, "never checked", "none", cadence_days)
    next_due = last_checked + timedelta(days=cadence_days)
    if today >= next_due:
        reason = f"last checked {last_checked.isoformat()}, cadence {cadence_days}d"
        return SourceDecision(slug, source_type, True, reason, last_checked.isoformat(), cadence_days)
    reason = f"checked {last_checked.isoformat()}, next due {next_due.isoformat()}"
    return SourceDecision(slug, source_type, False, reason, last_checked.isoformat(), cadence_days)


def decide_sources(brain_root: Path, today: date) -> list[SourceDecision]:
    sources_dir = brain_root / "WIP" / "SOURCES"
    registry_path = sources_dir / "sources.registry.md"
    decisions: list[SourceDecision] = []
    for entry in enabled_sources(registry_path):
        descriptor_path = descriptor_path_for(sources_dir, entry.slug)
        decisions.append(decide_due(descriptor_path, today, entry.slug, entry.source_type))
    return decisions


def summarize_due_sources(brain_root: Path, today: date) -> list[str]:
    lines = []
    for decision in decide_sources(brain_root, today):
        if decision.due:
            type_label = decision.source_type or "unknown type"
            lines.append(f"- {decision.slug} ({type_label}): {decision.reason}")
    return lines


def mark_checked(descriptor_path: Path, today: date, status: str) -> None:
    if status not in VALID_STATUS:
        raise ValueError(f"invalid status: {status!r} (expected one of {VALID_STATUS})")
    if not descriptor_path.exists():
        raise FileNotFoundError(f"descriptor not found: {descriptor_path}")
    text = descriptor_path.read_text(encoding="utf-8")
    text, checked_count = re.subn(
        r"(?m)^- Last checked:.*$", f"- Last checked: {today.isoformat()}", text, count=1
    )
    text, status_count = re.subn(
        r"(?m)^- Last status:.*$", f"- Last status: {status}", text, count=1
    )
    if checked_count == 0 or status_count == 0:
        raise ValueError(
            f"descriptor missing 'Last checked:'/'Last status:' fields: {descriptor_path}"
        )
    descriptor_path.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Decide which sources are due for ingestion.")
    parser.add_argument("--brain-root", default=".", help="Brain root path")
    subparsers = parser.add_subparsers(dest="command")

    list_due = subparsers.add_parser("list-due", help="List due/not-due sources (default)")
    list_due.add_argument("--date", help="Override today's date as YYYY-MM-DD")
    list_due.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    mark = subparsers.add_parser("mark-checked", help="Record that a source was just checked")
    mark.add_argument("--source", required=True, help="Source slug, matching sources.<slug>.md")
    mark.add_argument("--status", required=True, choices=VALID_STATUS)
    mark.add_argument("--date", help="Override today's date as YYYY-MM-DD")

    args = parser.parse_args()
    if args.command is None:
        args.command = "list-due"
        args.date = None
        args.json = False
    return args


def main() -> int:
    args = parse_args()
    brain_root = Path(args.brain_root).expanduser().resolve()
    if not brain_root.is_dir():
        print(f"Brain root not found: {brain_root}")
        return 1
    today = date.fromisoformat(args.date) if args.date else datetime.now().date()

    if args.command == "mark-checked":
        descriptor_path = descriptor_path_for(brain_root / "WIP" / "SOURCES", args.source)
        try:
            mark_checked(descriptor_path, today, args.status)
        except (FileNotFoundError, ValueError) as error:
            print(f"mark-checked failed: {error}")
            return 1
        print(f"{args.source}: last checked {today.isoformat()}, status {args.status}")
        return 0

    decisions = decide_sources(brain_root, today)
    if args.json:
        print(json.dumps([decision.__dict__ for decision in decisions], ensure_ascii=False, indent=2))
    else:
        print("# Source scheduler")
        print(f"brain_root: {brain_root}")
        print(f"today: {today.isoformat()}")
        print()
        print("## Decisions")
        for decision in decisions:
            print(f"- {decision.slug} ({decision.source_type or 'unknown type'})")
            print(f"  due: {decision.due}")
            print(f"  reason: {decision.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

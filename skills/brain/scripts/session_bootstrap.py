#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
ACTION_CATEGORY_RE = re.compile(r"^\* \[\[([^\]]+)\]\]:\s*$")
WORK_PROJECT_RE = re.compile(r"^ {2}\* (.+?)\s*$")

TEMPLATE_CANDIDATES = [
    Path("TEMPLATES/Daily Note Template.md"),
    Path("TEMPLATES/TEMPLATE.daily-note.common.md"),
    Path("_COMMON/TEMPLATES/TEMPLATE.daily-note.common.md"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect vault state and print a ready-to-send session bootstrap prompt.")
    parser.add_argument("--brain-root", default=".", help="Vault root path")
    return parser.parse_args()


def load_daily_config(brain_root: Path) -> dict:
    path = brain_root / ".obsidian" / "daily-notes.json"
    if not path.exists():
        return {"folder": "JOURNAL"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"folder": "JOURNAL"}


def list_daily_notes(journal_root: Path) -> list[Path]:
    notes = []
    for p in journal_root.rglob("*.md"):
        if DATE_RE.match(p.name):
            notes.append(p)
    return sorted(notes, key=lambda path: (path.name, str(path)))


def list_session_notes(brain_root: Path) -> list[Path]:
    session_dir = brain_root / "WIP" / "SESSIONS"
    if not session_dir.exists():
        return []
    return sorted(session_dir.glob("*.md"))


def read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def find_template_path(brain_root: Path) -> Path | None:
    for candidate in TEMPLATE_CANDIDATES:
        path = brain_root / candidate
        if path.exists():
            return path
    return None


def action_categories(lines: list[str]) -> list[str]:
    categories: list[str] = []
    for line in lines:
        match = ACTION_CATEGORY_RE.match(line)
        if match:
            categories.append(match.group(1))
    return categories


def work_project_headings(lines: list[str]) -> list[str]:
    headings: list[str] = []
    in_actions = False
    in_work = False
    for line in lines:
        if line.startswith("# "):
            in_actions = line == "# Actions"
            in_work = False
            continue
        if not in_actions:
            continue
        category_match = ACTION_CATEGORY_RE.match(line)
        if category_match:
            in_work = category_match.group(1) == "WORK"
            continue
        if in_work:
            project_match = WORK_PROJECT_RE.match(line)
            if project_match:
                headings.append(project_match.group(1))
    return headings


def validate_daily_notes(brain_root: Path, journal_root: Path, daily_notes: list[Path], today_path: Path) -> list[str]:
    warnings: list[str] = []
    template_path = find_template_path(brain_root)
    if today_path.exists() and template_path:
        expected_categories = action_categories(read_lines(template_path))
        today_categories = set(action_categories(read_lines(today_path)))
        missing = [category for category in expected_categories if category not in today_categories]
        if missing:
            warnings.append(
                f"Current daily note `{today_path.relative_to(brain_root)}` is missing template action categories: "
                + ", ".join(f"[[{category}]]" for category in missing)
                + ". Current-day cleanup may have run too early."
            )
    for daily_note in daily_notes:
        headings = work_project_headings(read_lines(daily_note))
        seen: set[str] = set()
        duplicates: list[str] = []
        for heading in headings:
            if heading in seen and heading not in duplicates:
                duplicates.append(heading)
            seen.add(heading)
        if duplicates:
            warnings.append(
                f"Daily note `{daily_note.relative_to(brain_root)}` has duplicate WORK project section(s): "
                + ", ".join(f"`{heading}`" for heading in duplicates)
                + ". Merge same-project activity under one heading."
            )
    return warnings


def main() -> int:
    args = parse_args()
    brain_root = Path(args.brain_root).resolve()

    daily_config = load_daily_config(brain_root)
    journal_root = brain_root / daily_config["folder"]
    today = datetime.now().strftime("%Y-%m-%d")

    daily_notes = list_daily_notes(journal_root)
    latest_daily = daily_notes[-1].name if daily_notes else "NONE"
    today_path = journal_root / f"{today}.md"
    today_exists = today_path.exists()
    sessions = list_session_notes(brain_root)
    daily_warnings = validate_daily_notes(brain_root, journal_root, daily_notes, today_path)

    print("# Session bootstrap")
    print()
    print(f"brain_root: {brain_root}")
    print(f"journal_folder: {journal_root.relative_to(brain_root)}")
    print(f"today: {today}")
    print(f"today_daily_exists: {'yes' if today_exists else 'no'}")
    print(f"latest_daily: {latest_daily}")
    print("open_session_notes:")
    if sessions:
        for s in sessions:
            print(f"- {s.relative_to(brain_root)}")
    else:
        print("- none found")
    print("daily_note_warnings:")
    if daily_warnings:
        for warning in daily_warnings:
            print(f"- {warning}")
    else:
        print("- none found")

    print()
    print("# Recommended kickoff prompt")
    print()
    print("New clean session bootstrap.")
    print(f"- Today: {today}")
    print(f"- Today daily exists: {'yes' if today_exists else 'no'}")
    print(f"- Latest daily note found: {latest_daily}")
    if sessions:
        print("- Existing session notes:")
        for s in sessions:
            print(f"  - {s.relative_to(brain_root)}")
    else:
        print("- Existing session notes: none found")
    print(
        "Please run the session-start protocol in RULES-SESSION-LIFECYCLE.md -> Flow 2 (the rule is the single source of truth for the exact steps):"
    )
    if not today_exists:
        print(
            "- Today's daily note is MISSING (Scenario B): close the previous day first "
            "(review-first TODO carry-over + Objectives review, then empty-category cleanup scoped to the previous daily -- "
            "DEFER that cleanup if the previous day still has open session notes pending consolidation), "
            "then create today's daily note with navigation links."
        )
    else:
        print("- Today's daily note already EXISTS (Scenario A): do not re-clean or restructure it.")
    print("- Review the daily-note warnings above before modifying JOURNAL.")
    print("- Create the new session note with the real session id and add it to today's `# Sessions`.")
    print(
        "- For the OTHER open session notes listed above, apply the State-driven 'Previous sessions rollover': "
        "read each note's `## State` / `## Immediate next step` -- consolidate the clearly-finished ones into the right "
        "daily/WIP/BACKLOG/MEMORY (by the day the work happened) and close them after the closing gate; leave live or "
        "ambiguous ones untouched and just report them. Never consolidate or close a session that may still be active."
    )
    print("- Summarize the active WIP context before continuing work.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Collect what happened in a brain over a date range, as JSON, for the daily report.

Read-only: it never writes to the brain. It gathers the raw material (daily notes,
session notes, issue notes, generated deliverables) and attributes each piece to the
day it belongs to; composing the report from it is the calling agent's job.

`issues` lists only issue notes touched in range (a dated entry or a modification date in
range). Generated files are attributed against every issue note, touched or not, by
explicit path or folder reference; issue notes referenced that way but not touched are
listed separately in `referenced_issues` as context, never as activity.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from session_open_discovery import (  # noqa: E402
    JournalConfigError,
    is_session_note_empty,
    list_daily_notes,
    list_session_notes,
    load_journal_folder,
    read_text_safe,
    session_note_date,
)

ISSUE_ROOTS = ("WIP", "MEMORY/Projects")
DEFAULT_SCAN_DIRS = ("OUTBOX",)
RESUME_ID_RE = re.compile(r"(?:--resume|--conversation|resume|-s)\s+([0-9A-Za-z][0-9A-Za-z._-]*)")
SESSION_LINK_RE = re.compile(r"Session note:\s*\[\[([^\]|]+)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
DATED_HEADING_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b[\s:—–-]*(.*)$")
FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*(?:#.*)?$")
PLACEHOLDER_RE = re.compile(r"^-?\s*$")
MAX_STATUS_CHARS = 3000


def _iso(value: date) -> str:
    return value.isoformat()


def _mtime_date(path: Path) -> date:
    return datetime.fromtimestamp(path.stat().st_mtime).date()


def _rel(brain_root: Path, path: Path) -> str:
    return path.relative_to(brain_root).as_posix()


def _in_range(value: date | None, start: date, end: date) -> bool:
    return value is not None and start <= value <= end


def split_frontmatter(text: str) -> tuple[dict[str, str], list[str]]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, lines
    meta: dict[str, str] = {}
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return meta, lines[index + 1 :]
        match = FRONTMATTER_KEY_RE.match(lines[index])
        if match:
            meta[match.group(1)] = match.group(2).strip()
    return {}, lines


def section(lines: list[str], title: str, level: int = 2) -> list[str]:
    """Body lines of the first heading named `title`, up to the next heading of the same or higher level."""
    body: list[str] = []
    inside = False
    for line in lines:
        match = HEADING_RE.match(line)
        if match:
            depth = len(match.group(1))
            if inside and depth <= level:
                break
            if not inside and depth == level and match.group(2).strip().lower() == title.lower():
                inside = True
                continue
        if inside:
            body.append(line)
    return body


def _meaningful(lines: list[str]) -> list[str]:
    return [line.rstrip() for line in lines if not PLACEHOLDER_RE.match(line.strip())]


def parse_daily(path: Path) -> dict[str, object]:
    lines = split_frontmatter(read_text_safe(path))[1]
    sessions = []
    for line in section(lines, "Sessions", level=1):
        if not line.startswith("- "):
            continue
        resume = RESUME_ID_RE.search(line)
        link = SESSION_LINK_RE.search(line)
        sessions.append(
            {
                "session_id": resume.group(1) if resume else None,
                "note": link.group(1) if link else None,
                "line": line[2:].strip(),
            }
        )
    work: list[str] = []
    collecting = False
    for line in section(lines, "Actions", level=1):
        if line.startswith("* [["):
            collecting = line.startswith("* [[WORK]]")
            continue
        if collecting and not PLACEHOLDER_RE.match(line.strip()):
            work.append(line.rstrip())
    return {"date": path.stem, "path": path.as_posix(), "sessions": sessions, "work": work}


def _find_session_note(brain_root: Path, session_id: str | None, link: str | None) -> Path | None:
    candidates = list(list_session_notes(brain_root))
    trash = brain_root / "QUARANTINE" / "TRASH"
    if trash.exists():
        candidates += sorted(trash.glob("*-session-*.md"))
    for path in candidates:
        if link and path.stem == link:
            return path
    for path in candidates:
        if session_id and f"-session-{session_id}-" in path.name:
            return path
    return None


def parse_session_note(brain_root: Path, path: Path) -> dict[str, object]:
    lines = split_frontmatter(read_text_safe(path))[1]
    status = ""
    for line in section(lines, "State"):
        match = re.match(r"^-\s+Status:\s*(\S+)", line.strip())
        if match:
            status = match.group(1).lower()
            break
    return {
        "path": _rel(brain_root, path),
        "status": status,
        "empty": is_session_note_empty(path),
        "objective": _meaningful(section(lines, "Current objective")),
        "next_step": _meaningful(section(lines, "Immediate next step")),
        "open_questions": _meaningful(section(lines, "Open questions")),
        "modified": _iso(_mtime_date(path)),
    }


def dated_entries(lines: list[str], start: date, end: date) -> list[dict[str, object]]:
    """Dated sub-headings (`### 2026-10-09: …`) inside a note, with their bodies, filtered by range."""
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    current_depth = 0
    for line in lines:
        match = HEADING_RE.match(line)
        if match:
            depth = len(match.group(1))
            if current is not None and depth <= current_depth:
                entries.append(current)
                current = None
            dated = DATED_HEADING_RE.match(match.group(2))
            if dated and 2 <= depth <= 4:
                current = {"date": dated.group(1), "title": dated.group(2).strip(), "lines": []}
                current_depth = depth
                continue
        if current is not None:
            current["lines"].append(line.rstrip())  # type: ignore[union-attr]
    if current is not None:
        entries.append(current)
    kept = []
    for entry in entries:
        try:
            entry_date = date.fromisoformat(str(entry["date"]))
        except ValueError:
            continue
        if start <= entry_date <= end:
            entry["lines"] = _meaningful(entry["lines"])  # type: ignore[arg-type]
            kept.append(entry)
    return kept


@dataclass(frozen=True, slots=True)
class IssueNote:
    path: Path
    meta: dict[str, str]
    body: list[str]
    text: str

    @property
    def issue_id(self) -> str:
        return self.meta["issue_id"]

    @property
    def is_primary(self) -> bool:
        return self.path.stem == self.path.parent.name


def scan_issue_notes(brain_root: Path) -> list[IssueNote]:
    """Every note carrying an `issue_id`, touched or not; the base for activity and attribution."""
    notes: list[IssueNote] = []
    for root_name in ISSUE_ROOTS:
        root = brain_root / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            if "SESSIONS" in path.parts:
                continue
            text = read_text_safe(path)
            if not text.startswith("---"):
                continue
            meta, body = split_frontmatter(text)
            if not meta.get("issue_id"):
                continue
            notes.append(IssueNote(path, meta, body, text))
    return notes


def collect_issues(
    brain_root: Path, start: date, end: date, notes: list[IssueNote] | None = None
) -> list[dict[str, object]]:
    """Issue notes touched in range. Facet files (`<id>.analysis.md`, evidence, drafts) that share the
    `issue_id` of a primary `folder/folder.md` note are attached to it as `facets`; a facet whose
    primary note was not touched stays a standalone item so its activity is not lost."""
    issues: list[dict[str, object]] = []
    facets: list[dict[str, object]] = []
    for note in notes if notes is not None else scan_issue_notes(brain_root):
        entries = dated_entries(note.body, start, end)
        touched = _in_range(_mtime_date(note.path), start, end)
        if not entries and not touched:
            continue
        status_text = "\n".join(_meaningful(section(note.body, "Status")))
        summary = next((line[1:].strip() for line in note.body if line.startswith(">")), "")
        item = {
            "issue_id": note.issue_id,
            "path": _rel(brain_root, note.path),
            "status": note.meta.get("status", ""),
            "work_type": note.meta.get("work_type", ""),
            "url": note.meta.get("url", ""),
            "summary": summary,
            "dated_entries": entries,
            "status_section": status_text[:MAX_STATUS_CHARS],
            "modified": _iso(_mtime_date(note.path)),
            "facets": [],
        }
        (issues if note.is_primary else facets).append(item)
    for facet in facets:
        primary = next((i for i in issues if i["issue_id"] == facet["issue_id"]), None)
        if primary is None:
            issues.append(facet)
        else:
            primary["facets"].append(facet["path"])  # type: ignore[union-attr]
    return sorted(issues, key=lambda item: str(item["issue_id"]))


def _normalize_reference_text(text: str) -> str:
    """Spellings that name the same path: URL-encoded spaces in Markdown link targets."""
    return text.replace("%20", " ")


def _reference_candidates(rel_path: str, scan_dirs: frozenset[str]) -> list[str]:
    """The file's own path and its folder ancestors, minus top-level and scan-root folders
    (too generic to prove a reference). Independent of which scan root found the file."""
    parts = rel_path.split("/")
    candidates = [rel_path]
    for end_index in range(len(parts) - 1, 1, -1):
        folder = "/".join(parts[:end_index])
        if folder not in scan_dirs:
            candidates.append(folder)
    return candidates


def _mentions_path(text: str, candidate: str) -> bool:
    """True when `candidate` appears as a whole path: not glued to other path characters, and
    `OUTBOX/x` never matches `OUTBOX/x-old` or `OUTBOX/x.bak`."""
    pattern = r"(?<![\w./-])" + re.escape(candidate) + r"(?![\w-])(?!\.\w)"
    return re.search(pattern, text) is not None


def collect_generated_files(
    brain_root: Path,
    scan_dirs: list[str],
    start: date,
    end: date,
    issue_texts: dict[str, str],
) -> list[dict[str, object]]:
    """Files generated in range under the scan dirs, with the issue ids whose notes reference
    the file's path or one of its folders. `issue_texts` maps every issue id to the text of all
    its notes, touched or not. Overlapping scan dirs list a file once."""
    normalized = list(dict.fromkeys(name.strip("/") for name in scan_dirs if name.strip("/")))
    generic = frozenset(normalized)
    texts = {iid: _normalize_reference_text(text) for iid, text in issue_texts.items()}
    found: dict[str, dict[str, object]] = {}
    for name in normalized:
        root = brain_root / name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name == ".DS_Store":
                continue
            rel = _rel(brain_root, path)
            if rel in found or not _in_range(_mtime_date(path), start, end):
                continue
            candidates = _reference_candidates(rel, generic)
            found[rel] = {
                "path": rel,
                "modified": _iso(_mtime_date(path)),
                "size": path.stat().st_size,
                "referenced_by": sorted(
                    iid
                    for iid, text in texts.items()
                    if any(_mentions_path(text, candidate) for candidate in candidates)
                ),
            }
    return [found[rel] for rel in sorted(found)]


def collect_referenced_issues(
    brain_root: Path,
    notes: list[IssueNote],
    issues: list[dict[str, object]],
    generated_files: list[dict[str, object]],
    warnings: list[str],
) -> list[dict[str, object]]:
    """Existing issue notes that in-range files point at but that were not touched in range:
    context for the report, never activity. The primary note supplies the metadata."""
    touched = {str(item["issue_id"]) for item in issues}
    wanted = sorted(
        {str(iid) for file in generated_files for iid in file["referenced_by"]} - touched  # type: ignore[union-attr]
    )
    referenced = []
    for issue_id in wanted:
        group = sorted((n for n in notes if n.issue_id == issue_id), key=lambda n: str(n.path))
        primaries = [n for n in group if n.is_primary]
        chosen = (primaries or group)[0]
        if len({(n.meta.get("work_type", ""), n.meta.get("status", "")) for n in primaries}) > 1:
            warnings.append(
                f"issue {issue_id}: several primary notes disagree on work_type/status; "
                f"using {_rel(brain_root, chosen.path)}"
            )
        referenced.append(
            {
                "issue_id": issue_id,
                "path": _rel(brain_root, chosen.path),
                "work_type": chosen.meta.get("work_type", ""),
                "status": chosen.meta.get("status", ""),
            }
        )
    return referenced


def default_start(daily_dates: list[date], today: date) -> date | None:
    earlier = [value for value in daily_dates if value < today]
    return max(earlier) if earlier else None


def collect(
    brain_root: Path,
    start: date | None,
    end: date,
    today: date,
    scan_dirs: list[str] | None = None,
) -> dict[str, object]:
    journal_root = brain_root / load_journal_folder(brain_root)
    daily_paths = {date.fromisoformat(p.stem): p for p in list_daily_notes(journal_root)}
    warnings: list[str] = []
    if start is None:
        start = default_start(list(daily_paths), today)
        if start is None:
            raise ValueError("no daily note before today; pass --from")
    if start > end:
        raise ValueError(f"--from {start} is after --to {end}")

    days = [parse_daily(path) for day, path in sorted(daily_paths.items()) if start <= day <= end]
    missing_dailies = [] if daily_paths.get(start) else [_iso(start)]

    registered: dict[str, dict[str, object]] = {}
    for day in days:
        for entry in day["sessions"]:  # type: ignore[union-attr]
            key = str(entry["session_id"] or entry["note"])
            registered.setdefault(key, {"entry": entry, "days": []})["days"].append(day["date"])  # type: ignore[union-attr]

    sessions = []
    seen_paths: set[Path] = set()
    for key, info in registered.items():
        entry = info["entry"]  # type: ignore[assignment]
        note = _find_session_note(brain_root, entry["session_id"], entry["note"])  # type: ignore[index]
        if note is None:
            warnings.append(f"session {key}: registered in a daily but its note was not found")
            continue
        seen_paths.add(note)
        sessions.append(
            {"session_id": entry["session_id"], "registered_in": info["days"], "reason": "registered", **parse_session_note(brain_root, note)}  # type: ignore[index]
        )
    for note in list_session_notes(brain_root):
        if note in seen_paths:
            continue
        reasons = []
        if _in_range(
            date.fromisoformat(session_note_date(note)) if session_note_date(note) else None, start, end
        ):
            reasons.append("created-in-range")
        if _in_range(_mtime_date(note), start, end):
            reasons.append("modified-in-range")
        if reasons:
            sessions.append(
                {"session_id": None, "registered_in": [], "reason": "+".join(reasons), **parse_session_note(brain_root, note)}
            )

    notes = scan_issue_notes(brain_root)
    issues = collect_issues(brain_root, start, end, notes)
    issue_texts: dict[str, list[str]] = {}
    for note in notes:
        issue_texts.setdefault(note.issue_id, []).append(note.text)
    generated_files = collect_generated_files(
        brain_root,
        scan_dirs or list(DEFAULT_SCAN_DIRS),
        start,
        end,
        {iid: "\n".join(texts) for iid, texts in issue_texts.items()},
    )
    referenced_issues = collect_referenced_issues(brain_root, notes, issues, generated_files, warnings)
    return {
        "range": {"from": _iso(start), "to": _iso(end), "today": _iso(today)},
        "days": days,
        "missing_dailies": missing_dailies,
        "sessions": sessions,
        "issues": issues,
        "referenced_issues": referenced_issues,
        "generated_files": generated_files,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brain-root", required=True, type=Path)
    parser.add_argument("--from", dest="start", help="first day, YYYY-MM-DD (default: latest daily before today)")
    parser.add_argument("--to", dest="end", help="last day, YYYY-MM-DD (default: today)")
    parser.add_argument("--today", help="override today's date, YYYY-MM-DD (tests)")
    parser.add_argument("--scan-dir", action="append", help="extra brain-relative dir of generated files to scan (default: OUTBOX)")
    args = parser.parse_args(argv)
    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
        start = date.fromisoformat(args.start) if args.start else None
        end = date.fromisoformat(args.end) if args.end else today
        scan_dirs = list(DEFAULT_SCAN_DIRS) + (args.scan_dir or [])
        result = collect(args.brain_root.resolve(), start, end, today, scan_dirs)
    except (ValueError, JournalConfigError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

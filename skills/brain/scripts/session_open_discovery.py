from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path


DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
STATUS_RE = re.compile(r"^-\s+Status:\s*(.+)$")
TEMPLATE_CANDIDATES = [
    Path("TEMPLATES/TEMPLATE.wip-session.common.md"),
    Path("_COMMON/TEMPLATES/TEMPLATE.wip-session.common.md"),
]
DAILY_TEMPLATE_CANDIDATES = [
    Path("TEMPLATES/Daily Note Template.md"),
    Path("TEMPLATES/TEMPLATE.daily-note.common.md"),
    Path("_COMMON/TEMPLATES/TEMPLATE.daily-note.common.md"),
]


class JournalConfigError(ValueError):
    pass


def load_journal_folder(brain_root: Path) -> str:
    config_path = brain_root / ".obsidian" / "daily-notes.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            raise JournalConfigError(
                f"invalid journal configuration {config_path}: {exc}"
            ) from exc
    else:
        cfg = {}
    if not isinstance(cfg, dict):
        raise JournalConfigError(
            f"invalid journal configuration {config_path}: expected a JSON object"
        )
    folder = cfg.get("folder", "JOURNAL")
    if not isinstance(folder, str):
        raise JournalConfigError(
            f"invalid journal configuration {config_path}: folder must be a string"
        )
    configured = Path(folder)
    if not folder or configured.is_absolute() or ".." in configured.parts:
        raise JournalConfigError(
            f"invalid journal configuration {config_path}: folder must stay within the brain"
        )
    resolved_brain = brain_root.resolve(strict=False)
    try:
        (resolved_brain / configured).resolve(strict=False).relative_to(resolved_brain)
    except ValueError as exc:
        raise JournalConfigError(
            f"invalid journal configuration {config_path}: folder escapes the brain"
        ) from exc
    return configured.as_posix()


def list_daily_notes(journal_root: Path) -> list[Path]:
    notes = []
    for path in journal_root.rglob("*.md"):
        if DATE_RE.match(path.name):
            notes.append(path)
    return sorted(notes, key=lambda path: (path.name, str(path)))


def list_session_notes(brain_root: Path) -> list[Path]:
    session_dir = brain_root / "WIP" / "SESSIONS"
    if not session_dir.exists():
        return []
    return sorted(session_dir.glob("*.md"))


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def read_lines_safe(path: Path) -> list[str]:
    return read_text_safe(path).splitlines()


def find_template(brain_root: Path) -> Path | None:
    for candidate in TEMPLATE_CANDIDATES:
        path = brain_root / candidate
        if path.exists():
            return path
    return None


def find_daily_template(brain_root: Path) -> Path | None:
    """Return the preferred daily template, refusing a local/common divergence."""
    existing = [brain_root / candidate for candidate in DAILY_TEMPLATE_CANDIDATES]
    existing = [path for path in existing if path.exists()]
    if not existing:
        return None
    local = brain_root / DAILY_TEMPLATE_CANDIDATES[0]
    common = next((path for path in existing[1:] if path.exists()), None)
    if local.exists() and common is not None:
        same_target = False
        try:
            same_target = local.resolve() == common.resolve()
        except OSError:
            pass
        if not same_target and read_text_safe(local) != read_text_safe(common):
            raise ValueError(
                "local and common daily templates diverge; reconcile them before creating "
                "today's daily"
            )
    return existing[0]


def _read_note_lossy(path: Path) -> str:
    """Read a peer note for Status detection: bad bytes never abort session-open."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_note_strict(path: Path) -> str | None:
    """Read a peer note, or None when it cannot be read or decoded (no evidence)."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def is_session_open(note_path: Path) -> bool:
    for line in _read_note_lossy(note_path).splitlines():
        match = STATUS_RE.match(line.strip())
        if match:
            return match.group(1).strip().lower() == "open"
    return False


SESSION_NOTE_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-session-")
PLACEHOLDER_ITEM_RE = re.compile(r"^-\s*$")
UNCHECKED_BOX_RE = re.compile(r"^- \[ \]")
CHECKLIST_SECTION = "Consolidation checklist"
SHELL_SECTIONS = frozenset({"State", "Resume command"})
HEADING_RE = re.compile(r"^#{1,3} +(.+?)\s*$")
COMMENT_SPAN_RE = re.compile(r"<!--.*?-->")


def session_note_date(note_path: Path) -> str | None:
    match = SESSION_NOTE_DATE_RE.match(note_path.name)
    return match.group(1) if match else None


def is_session_note_empty(note_path: Path) -> bool:
    """Classify a session note as never-worked (scaffold only) or worked.

    Never counts as work: frontmatter (only at line 0, per the note format),
    HTML comments (single- or multi-line), headings, the State/Resume command
    shell sections, blank lines, bare ``-`` placeholders, and unchecked boxes
    inside the template's Consolidation checklist. Any other content —
    including a mid-document ``---`` rule — marks the note worked; on any
    parse doubt (unclosed frontmatter or comment, or a note that cannot be
    read or decoded) the note is reported worked, so the flag never fires on
    ambiguity.
    """
    text = _read_note_strict(note_path)
    if text is None:
        return False
    lines = text.splitlines()
    in_frontmatter = False
    frontmatter_closed = False
    in_comment = False
    section = ""
    for line_no, raw in enumerate(lines):
        line = raw.rstrip("\n")
        stripped = line.strip()
        is_frontmatter_delim = stripped == "---"
        if (
            line_no == 0
            and not frontmatter_closed
            and is_frontmatter_delim
        ):
            in_frontmatter = True
            continue
        if in_frontmatter:
            if is_frontmatter_delim:
                in_frontmatter = False
                frontmatter_closed = True
            continue
        if in_comment:
            if "-->" in stripped:
                after = stripped.split("-->", 1)[1].strip()
                in_comment = False
                if not after:
                    continue
                stripped = after
            else:
                continue
        elif stripped.startswith("<!--"):
            if "-->" in stripped:
                after = stripped.split("-->", 1)[1].strip()
                if not after:
                    continue
                stripped = after
            else:
                in_comment = True
                continue
        heading = HEADING_RE.match(line)
        if heading:
            section = heading.group(1).strip()
            continue
        if not stripped:
            continue
        if section in SHELL_SECTIONS:
            continue
        if PLACEHOLDER_ITEM_RE.match(stripped):
            continue
        if (
            section == CHECKLIST_SECTION
            and UNCHECKED_BOX_RE.match(stripped)
        ):
            continue
        return False
    if in_frontmatter or in_comment:
        return False
    return True


NEXT_STEP_HEADING = "immediate next step"
NEXT_STEP_SECTION_END_RE = re.compile(r"^#{1,2} +\S")
NESTED_HEADING_RE = re.compile(r"^#{3,6} +\S")
NEXT_STEP_CLOSURES = frozenset({"none", "session closed"})
LIST_MARKER_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
CHECKBOX_RE = re.compile(r"^\[[ xX]\]\s*")

NEXT_STEP_PRESENT = "present"
NEXT_STEP_NONE = "none"
NEXT_STEP_MISSING = "missing"
NEXT_STEP_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SessionRolloverFacts:
    """Mechanical facts about a peer note; policy stays in the lifecycle rule."""

    next_step: str


def _next_step_lines(lines: list[str]) -> list[str] | None:
    """Body of the single `## Immediate next step` section, or None when the
    structure cannot be trusted (duplicate section, unclosed comment or fence)."""
    sections: list[list[str]] = []
    current: list[str] | None = None
    in_fence = False
    in_comment = False
    for raw in lines:
        stripped = raw.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            continue
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if NEXT_STEP_SECTION_END_RE.match(raw):
            heading = HEADING_RE.match(raw)
            if (
                raw.startswith("## ")
                and heading is not None
                and heading.group(1).strip().lower() == NEXT_STEP_HEADING
            ):
                current = []
                sections.append(current)
            else:
                current = None
            continue
        if NESTED_HEADING_RE.match(raw):
            continue
        if current is not None:
            current.append(stripped)
    if in_comment or in_fence or len(sections) > 1:
        return None
    return sections[0] if sections else []


def read_session_rollover_facts(note_path: Path) -> SessionRolloverFacts:
    """Classify the `## Immediate next step` of a peer note.

    present: meaningful pending content. none: only an exact closure item
    (`none`, `session closed`). missing: no section, or only blanks, bare `-`
    and comments. unknown: unreadable or undecodable note, duplicate section,
    unclosed comment/fence, or closure and pending content together.
    """
    text = _read_note_strict(note_path)
    if text is None:
        return SessionRolloverFacts(NEXT_STEP_UNKNOWN)
    body = _next_step_lines(text.splitlines())
    if body is None:
        return SessionRolloverFacts(NEXT_STEP_UNKNOWN)
    closure = pending = False
    for line in body:
        item = CHECKBOX_RE.sub("", LIST_MARKER_RE.sub("", line)).strip()
        if not item or item == "-":
            continue
        if item.lower().rstrip(".") in NEXT_STEP_CLOSURES:
            closure = True
        else:
            pending = True
    if closure and pending:
        return SessionRolloverFacts(NEXT_STEP_UNKNOWN)
    if pending:
        return SessionRolloverFacts(NEXT_STEP_PRESENT)
    if closure:
        return SessionRolloverFacts(NEXT_STEP_NONE)
    return SessionRolloverFacts(NEXT_STEP_MISSING)


def open_session_next_steps(
    brain_root: Path,
    open_sessions: tuple[str, ...],
    empty: frozenset[str],
    exclude: frozenset[str],
) -> tuple[tuple[str, str], ...]:
    """(path, next_step) for non-empty peers; the current note is never included."""
    return tuple(
        (rel, read_session_rollover_facts(brain_root / rel).next_step)
        for rel in open_sessions
        if rel not in empty and rel not in exclude
    )


def empty_open_session_paths(
    brain_root: Path,
    open_sessions: tuple[str, ...],
    today: str,
    exclude: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    flagged: list[str] = []
    for rel in open_sessions:
        if rel in exclude:
            continue
        note_path = brain_root / rel
        note_day = session_note_date(note_path)
        if note_day is None or note_day >= today:
            continue
        if is_session_note_empty(note_path):
            flagged.append(rel)
    return tuple(flagged)


def _read_status(path: Path) -> str:
    for line in read_lines_safe(path):
        match = STATUS_RE.match(line.strip())
        if match:
            return match.group(1).strip().lower()
    return ""


def read_session_status(path: Path) -> str:
    """Public status reader for flow-level resume guards."""
    return _read_status(path)


def find_existing_session_note(brain_root: Path, session_id: str) -> Path | None:
    """Return the most recent active session note for session_id."""
    session_dir = brain_root / "WIP" / "SESSIONS"
    if not session_dir.exists():
        return None
    matches = [path for path in session_dir.glob("*.md") if session_id in path.name]
    if not matches:
        return None
    active = sorted(
        [
            path
            for path in matches
            if _read_status(path) in ("open", "handoff-only")
        ],
        reverse=True,
    )
    return active[0] if active else sorted(matches, reverse=True)[0]


def find_daily_neighbors(
    journal_root: Path,
    daily_path: Path,
    day: str,
) -> tuple[Path | None, Path | None]:
    """Return the nearest existing daily notes before and after day."""
    current = date.fromisoformat(day)
    dated_paths: dict[date, Path] = {}
    for path in list_daily_notes(journal_root):
        if path == daily_path:
            continue
        note_day = date.fromisoformat(path.stem)
        if note_day == current:
            raise ValueError(
                f"multiple daily notes found for {day}: {daily_path} and {path}"
            )
        if note_day in dated_paths:
            raise ValueError(
                f"multiple daily notes found for {note_day}: "
                f"{dated_paths[note_day]} and {path}"
            )
        dated_paths[note_day] = path
    previous_days = [note_day for note_day in dated_paths if note_day < current]
    next_days = [note_day for note_day in dated_paths if note_day > current]
    previous = dated_paths[max(previous_days)] if previous_days else None
    following = dated_paths[min(next_days)] if next_days else None
    return previous, following

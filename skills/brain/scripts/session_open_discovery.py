from __future__ import annotations

import json
import re
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


def is_session_open(note_path: Path) -> bool:
    for line in read_lines_safe(note_path):
        match = STATUS_RE.match(line.strip())
        if match:
            return match.group(1).strip().lower() == "open"
    return False


def _read_status(path: Path) -> str:
    for line in read_lines_safe(path):
        match = STATUS_RE.match(line.strip())
        if match:
            return match.group(1).strip().lower()
    return ""


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

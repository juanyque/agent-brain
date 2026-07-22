#!/usr/bin/env python3
"""Session-open ceremony script.

Single-script replacement for the ~15 Read/Bash calls that opening a vault session used to require.

1. Resolves vault state (daily notes, open sessions, warnings).
2. Reads context files and emits a compact digest (<30 lines).
3. (--prepare-daily) Prepares today's daily note after rollover decisions are complete.
4. (--apply) Creates the session note from TEMPLATE.wip-session.common.md.
5. (--apply) Upserts the session entry in today's daily note # Sessions block.
6. Verifies the session/daily postconditions after apply.

Dry-run by default; pass --apply to write files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_SCRIPTS = REPO_ROOT / "model" / "SCRIPTS"
if str(MODEL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MODEL_SCRIPTS))

from brain_state import current_brain_status, current_model_root  # noqa: E402


DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
DAILY_NAVIGATION_RE = re.compile(
    r"^(?P<prefix>\s*\[\[)"
    r"(?P<previous>\d{4}-\d{2}-\d{2})"
    r"(?P<middle>\]\][^\[\r\n]*\[\[)"
    r"(?P<next>\d{4}-\d{2}-\d{2})"
    r"(?P<suffix>\]\][^\[\r\n]*)"
    r"(?P<newline>\r?\n?)$"
)
SESSIONS_HEADER_RE = re.compile(r"^# Sessions\s*$")
HEADING_RE = re.compile(r"^#{1,3} ")
TASK_TYPE_ITEM_RE = re.compile(r"^- \[\[")
STATUS_RE = re.compile(r"^-\s+Status:\s*(.+)$")
SESSION_SCAFFOLD_PREFIXES = (
    "- REPLACE WITH REAL SESSION_ID",
    "- Example (OpenCode):",
    "- Example (Claude Code):",
    "- Example (Codex):",
)
SESSION_NOTE_REFERENCE_RE = re.compile(r"Session note:\s*\[\[[^\]]+\]\]\.?")

TEMPLATE_CANDIDATES = [
    Path("TEMPLATES/TEMPLATE.wip-session.common.md"),
    Path("_COMMON/TEMPLATES/TEMPLATE.wip-session.common.md"),
]

DAILY_TEMPLATE_CANDIDATES = [
    Path("TEMPLATES/Daily Note Template.md"),
    Path("TEMPLATES/TEMPLATE.daily-note.common.md"),
    Path("_COMMON/TEMPLATES/TEMPLATE.daily-note.common.md"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Session-open ceremony: resolve vault state, create session note, update daily."
    )
    parser.add_argument("--brain-root", required=True, help="Vault root path.")
    parser.add_argument(
        "--session-id",
        required=True,
        help="Session ID from the agent runtime. Resolve the REAL id before calling: "
        "Claude Code reads $CLAUDE_CODE_SESSION_ID; OpenCode runs `opencode session list`. "
        "Do not pass a timestamp fallback.",
    )
    parser.add_argument(
        "--runtime",
        default=None,
        choices=["claude", "opencode", "codex", "generic"],
        help="Agent runtime. Controls the resume-command format emitted in the session note "
        "and the daily # Sessions entry. If omitted, falls back to detect_runtime() "
        "(Claude via $CLAUDE_CODE_SESSION_ID, else 'generic'). Non-Claude runtimes MUST "
        "pass this explicitly so the resume command is correct.",
    )
    parser.add_argument(
        "--session-label",
        default="",
        help="Human-readable session label (e.g. from /rename). Used as topic slug.",
    )
    parser.add_argument(
        "--cwd",
        default="",
        help="Current working directory for WIP context filtering and the paste-ready "
        "session recovery command.",
    )
    parser.add_argument(
        "--prepare-daily",
        action="store_true",
        help="Create today's daily from the configured template when it is missing. "
        "Use only after the day-rollover review is complete. The created # Sessions "
        "block is empty and ready for deterministic registration.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write session note and upsert the daily registration. Default is dry-run.",
    )
    return parser.parse_args()


def detect_runtime() -> str:
    # Only Claude Code exposes a stable env var. OpenCode and others must be passed
    # explicitly via --runtime by the calling agent, which always knows its runtime.
    if os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "claude"
    return "generic"


def normalize_cwd(cwd: str) -> str:
    path = Path(cwd).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return str(path)


def resume_command(runtime: str, session_id: str, cwd: str = "") -> str:
    r = (runtime or "").strip().lower()
    if r == "claude":
        command = f"claude --resume {session_id}"
    elif r == "opencode":
        command = f"opencode -s {session_id}"
    elif r == "codex":
        command = f"codex resume {session_id}"
    else:
        # Never claim a wrong runtime: fall back to the bare id so the mistake is visible.
        return session_id
    if cwd:
        return f"cd {shlex.quote(normalize_cwd(cwd))} && {command}"
    return command


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def derive_topic(session_label: str, cwd: str, brain_root: Path) -> str:
    if session_label:
        slug = slugify(session_label)
        if slug:
            return slug
    if cwd:
        slug = slugify(Path(cwd).name)
        if slug:
            return slug
    slug = slugify(brain_root.name)
    if slug:
        return slug
    return f"unspecified-{datetime.now().strftime('%Y%m%d-%H%M')}"


def load_journal_folder(brain_root: Path) -> str:
    config_path = brain_root / ".obsidian" / "daily-notes.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            return cfg.get("folder", "JOURNAL")
        except Exception:
            pass
    return "JOURNAL"


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
        m = STATUS_RE.match(line.strip())
        if m:
            return m.group(1).strip().lower() == "open"
    return False


def _read_status(path: Path) -> str:
    for line in read_lines_safe(path):
        m = STATUS_RE.match(line.strip())
        if m:
            return m.group(1).strip().lower()
    return ""


def find_existing_session_note(brain_root: Path, session_id: str) -> Path | None:
    """Return the most recent active session note for session_id, regardless of date prefix.

    Used by --apply to avoid creating a duplicate when the same session continues
    across a day boundary. Returns the most recent open/handoff-only note, or None
    if no prior note exists for this session ID.
    """
    session_dir = brain_root / "WIP" / "SESSIONS"
    if not session_dir.exists():
        return None
    matches = [p for p in session_dir.glob("*.md") if session_id in p.name]
    if not matches:
        return None
    active = sorted(
        [p for p in matches if _read_status(p) in ("open", "handoff-only")],
        reverse=True,  # alphabetical desc = most-recent-first for date-prefixed names
    )
    return active[0] if active else sorted(matches, reverse=True)[0]


def extract_wip_context(wip_path: Path, cwd: str, max_headings: int = 5) -> list[str]:
    if not wip_path.exists():
        return []
    lines = read_lines_safe(wip_path)
    cwd_basename = ""
    keywords: set[str] = set()
    if cwd:
        cwd_basename = Path(cwd).name.lower()
        keywords.update(
            part
            for part in re.split(r"[^a-z0-9]+", cwd_basename)
            if len(part) > 2 and part not in {"all", "and", "for", "the", "with"}
        )

    result: list[str] = []
    seen = 0
    i = 0
    n = len(lines)
    while i < n and seen < max_headings:
        line = lines[i]
        if HEADING_RE.match(line):
            heading_lower = line.lower()
            heading_tokens = set(re.split(r"[^a-z0-9]+", heading_lower))
            relevant = (
                not keywords
                or cwd_basename in heading_lower
                or bool(keywords & heading_tokens)
            )
            if relevant:
                result.append(line)
                seen += 1
                j = i + 1
                child_count = 0
                while j < n and child_count < 3 and not HEADING_RE.match(lines[j]):
                    if lines[j].strip():
                        result.append(f"  {lines[j]}")
                        child_count += 1
                    j += 1
                i = j
                continue
        i += 1

    if not result and keywords:
        return extract_wip_context(wip_path, "", max_headings=3)
    return result


def extract_task_types(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in read_lines_safe(path) if TASK_TYPE_ITEM_RE.match(line)]


def instantiate_session_template(
    template_path: Path,
    date: str,
    topic: str,
    session_id: str,
    runtime: str,
    cwd: str,
) -> str:
    text = read_text_safe(template_path)
    text = text.replace(
        "# Session <date> / <topic> / <id>",
        f"# Session {date} / {topic} / {session_id}",
    )
    resume_lines = [
        "## Resume command",
        f"- `{resume_command(runtime, session_id, cwd)}`",
    ]
    if cwd:
        resume_lines.append(f"- Working directory: `{normalize_cwd(cwd)}`")
    resume_block = "\n".join(resume_lines)
    text = re.sub(
        r"## Resume command\n.*?(?=\n## |\Z)",
        resume_block + "\n",
        text,
        flags=re.DOTALL,
    )
    return text


def upsert_session_recovery(
    note_path: Path,
    session_id: str,
    runtime: str,
    cwd: str,
    apply: bool,
) -> str:
    """Make an existing session note's recovery block canonical and idempotent."""
    text = read_text_safe(note_path)
    if not text:
        return "missing-note"
    resume_lines = [
        "## Resume command",
        f"- `{resume_command(runtime, session_id, cwd)}`",
    ]
    if cwd:
        resume_lines.append(f"- Working directory: `{normalize_cwd(cwd)}`")
    replacement = "\n".join(resume_lines) + "\n"
    new_text, replacements = re.subn(
        r"## Resume command\n.*?(?=\n## |\Z)",
        replacement,
        text,
        count=1,
        flags=re.DOTALL,
    )
    if replacements == 0:
        return "missing-section"
    if new_text == text:
        return "unchanged"
    if apply:
        note_path.write_text(new_text, encoding="utf-8")
    return "updated"


def build_sessions_entry(
    session_id: str,
    topic: str,
    slug: str,
    runtime: str,
    cwd: str,
) -> str:
    label = topic.replace("-", "/") if topic else session_id[:8]
    return (
        f"- `{resume_command(runtime, session_id, cwd)}` — {label}. "
        f"Session note: [[{slug}]]."
    )


def _sessions_block_bounds(lines: list[str]) -> tuple[int, int] | None:
    header_idx = None
    for i, line in enumerate(lines):
        if SESSIONS_HEADER_RE.match(line.rstrip("\r\n")):
            header_idx = i
            break
    if header_idx is None:
        return None

    end_idx = header_idx + 1
    while end_idx < len(lines):
        stripped = lines[end_idx].rstrip("\r\n")
        if stripped.startswith("# ") and not SESSIONS_HEADER_RE.match(stripped):
            break
        end_idx += 1
    return header_idx, end_idx


def _is_sessions_scaffold(line: str) -> bool:
    return line.strip().startswith(SESSION_SCAFFOLD_PREFIXES)


def _entry_with_preserved_summary(existing: str, desired: str) -> str:
    """Refresh recovery metadata while preserving a user-edited summary."""
    desired_parts = desired.split("`", 2)
    start = existing.find("`")
    end = existing.find("`", start + 1) if start >= 0 else -1
    if len(desired_parts) == 3 and start >= 0 and end > start:
        newline = "\n" if existing.endswith("\n") else ""
        current = existing.rstrip("\r\n")
        current = current[: start + 1] + desired_parts[1] + current[end:]
        desired_reference = SESSION_NOTE_REFERENCE_RE.search(desired)
        existing_reference = SESSION_NOTE_REFERENCE_RE.search(current)
        if desired_reference and existing_reference:
            current = (
                current[: existing_reference.start()]
                + desired_reference.group(0)
                + current[existing_reference.end() :]
            )
        elif desired_reference:
            separator = " " if current.endswith((".", "!", "?")) else ". "
            current += separator + desired_reference.group(0)
        return current + newline
    return desired + ("\n" if existing.endswith("\n") else "")


def upsert_sessions_entry(
    daily_path: Path,
    entry: str,
    session_id: str,
    apply: bool,
) -> str:
    """Ensure exactly one canonical registration for session_id.

    Returns one of: missing-daily, missing-header, added, updated, unchanged.
    Known template scaffold lines are removed from # Sessions as part of the same
    deterministic update.
    """
    text = read_text_safe(daily_path)
    if not text:
        return "missing-daily"
    lines = text.splitlines(keepends=True)
    bounds = _sessions_block_bounds(lines)
    if bounds is None:
        return "missing-header"
    header_idx, end_idx = bounds

    body = lines[header_idx + 1 : end_idx]
    cleaned: list[str] = []
    found = 0
    scaffold_removed = False
    for line in body:
        if _is_sessions_scaffold(line):
            scaffold_removed = True
            continue
        if session_id in line:
            found += 1
            if found == 1:
                cleaned.append(_entry_with_preserved_summary(line, entry))
            continue
        cleaned.append(line)

    if found == 0:
        insert_idx = len(cleaned)
        while insert_idx > 0 and cleaned[insert_idx - 1].strip() == "":
            insert_idx -= 1
        cleaned.insert(insert_idx, entry + "\n")

    new_lines = lines[: header_idx + 1] + cleaned + lines[end_idx:]
    new_text = "".join(new_lines)
    changed = new_text != text
    if apply and changed:
        daily_path.write_text(new_text, encoding="utf-8")

    if found == 0:
        return "added"
    if changed or found > 1 or scaffold_removed:
        return "updated"
    return "unchanged"


def _daily_navigation_match(text: str) -> tuple[list[str], int, re.Match[str]]:
    lines = text.splitlines(keepends=True)
    matches = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := DAILY_NAVIGATION_RE.match(line)) is not None
    ]
    if len(matches) != 1:
        raise ValueError(
            "expected exactly one daily navigation line, "
            f"found {len(matches)}"
        )
    index, match = matches[0]
    return lines, index, match


def daily_navigation_targets(text: str) -> tuple[str, str]:
    """Return the previous and next daily-note targets from one navigation line."""
    _, _, match = _daily_navigation_match(text)
    return match.group("previous"), match.group("next")


def rewrite_daily_navigation(
    text: str,
    *,
    previous_day: str | None = None,
    next_day: str | None = None,
) -> str:
    """Replace selected navigation targets while preserving the line's formatting."""
    if previous_day is not None:
        date.fromisoformat(previous_day)
    if next_day is not None:
        date.fromisoformat(next_day)

    lines, index, match = _daily_navigation_match(text)
    previous = previous_day or match.group("previous")
    following = next_day or match.group("next")
    lines[index] = (
        f"{match.group('prefix')}{previous}{match.group('middle')}"
        f"{following}{match.group('suffix')}{match.group('newline')}"
    )
    return "".join(lines)


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


def instantiate_daily_template(
    template_path: Path,
    day: str,
    *,
    previous_day: str | None = None,
    next_day: str | None = None,
) -> str:
    """Instantiate navigation and leave # Sessions empty for script ownership."""
    current = date.fromisoformat(day)
    text = read_text_safe(template_path)
    text = text.replace("<% tp.date.yesterday() %>", str(current - timedelta(days=1)))
    text = text.replace("<% tp.date.tomorrow() %>", str(current + timedelta(days=1)))
    text = text.replace("<% tp.file.cursor() %>\n", "")
    text = rewrite_daily_navigation(
        text,
        previous_day=previous_day,
        next_day=next_day,
    )

    lines = text.splitlines(keepends=True)
    bounds = _sessions_block_bounds(lines)
    if bounds is None:
        raise ValueError("daily template has no # Sessions block")
    header_idx, end_idx = bounds
    body = [line for line in lines[header_idx + 1 : end_idx] if not _is_sessions_scaffold(line)]
    return "".join(lines[: header_idx + 1] + body + lines[end_idx:])


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _apply_daily_updates(
    updates: list[tuple[Path, str | None, str]],
) -> None:
    """Apply precomputed daily-note updates and restore originals on failure."""
    written: list[tuple[Path, str | None]] = []
    try:
        for path, original, content in updates:
            current = path.read_text(encoding="utf-8") if path.exists() else None
            if current != original:
                raise RuntimeError(f"daily note changed before write: {path}")
            if current == content:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            written.append((path, original))
            _write_text(path, content)
    except (OSError, RuntimeError) as exc:
        rollback_errors: list[str] = []
        for path, original in reversed(written):
            try:
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    _write_text(path, original)
            except OSError as rollback_exc:
                rollback_errors.append(f"{path}: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                "daily navigation update failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        raise


def prepare_daily_note(
    brain_root: Path,
    daily_path: Path,
    day: str,
    apply: bool,
) -> str:
    """Create today's daily deterministically; never overwrite an existing note."""
    if daily_path.exists():
        return "unchanged"
    template = find_daily_template(brain_root)
    if template is None:
        return "missing-template"

    journal_root = brain_root / load_journal_folder(brain_root)
    previous_path, next_path = find_daily_neighbors(journal_root, daily_path, day)
    current = date.fromisoformat(day)
    previous_day = previous_path.stem if previous_path else str(current - timedelta(days=1))
    next_day = next_path.stem if next_path else str(current + timedelta(days=1))
    content = instantiate_daily_template(
        template,
        day,
        previous_day=previous_day,
        next_day=next_day,
    )

    updates: list[tuple[Path, str | None, str]] = [(daily_path, None, content)]
    if previous_path is not None:
        previous_content = previous_path.read_text(encoding="utf-8")
        updates.append(
            (
                previous_path,
                previous_content,
                rewrite_daily_navigation(previous_content, next_day=day),
            )
        )
    if next_path is not None:
        next_content = next_path.read_text(encoding="utf-8")
        updates.append(
            (
                next_path,
                next_content,
                rewrite_daily_navigation(next_content, previous_day=day),
            )
        )

    if apply:
        _apply_daily_updates(updates)
    return "created" if apply else "would-create"


def validate_daily_navigation(
    journal_root: Path,
    daily_path: Path,
    day: str,
) -> list[str]:
    """Return violations in the daily note's reciprocal navigation chain."""
    errors: list[str] = []
    try:
        previous_path, next_path = find_daily_neighbors(journal_root, daily_path, day)
        previous_target, next_target = daily_navigation_targets(
            daily_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        return [f"daily navigation could not be validated: {exc}"]

    current = date.fromisoformat(day)
    expected_previous = (
        previous_path.stem if previous_path else str(current - timedelta(days=1))
    )
    expected_next = next_path.stem if next_path else str(current + timedelta(days=1))
    if previous_target != expected_previous:
        errors.append(
            f"daily previous link is {previous_target}, expected {expected_previous}"
        )
    if next_target != expected_next:
        errors.append(f"daily next link is {next_target}, expected {expected_next}")

    if previous_path is not None:
        try:
            _, previous_next = daily_navigation_targets(
                previous_path.read_text(encoding="utf-8")
            )
            if previous_next != day:
                errors.append(
                    f"previous daily {previous_path.name} points next to "
                    f"{previous_next}, expected {day}"
                )
        except (OSError, ValueError) as exc:
            errors.append(
                f"previous daily navigation could not be validated: {exc}"
            )

    if next_path is not None:
        try:
            next_previous, _ = daily_navigation_targets(
                next_path.read_text(encoding="utf-8")
            )
            if next_previous != day:
                errors.append(
                    f"next daily {next_path.name} points previous to "
                    f"{next_previous}, expected {day}"
                )
        except (OSError, ValueError) as exc:
            errors.append(f"next daily navigation could not be validated: {exc}")
    return errors


def validate_session_postconditions(
    daily_path: Path,
    session_note_path: Path,
    session_id: str,
    runtime: str,
    cwd: str,
) -> list[str]:
    """Return invariant violations after a session-open apply."""
    errors: list[str] = []
    expected_command = resume_command(runtime, session_id, cwd)
    if not session_note_path.exists():
        errors.append(f"session note missing: {session_note_path}")
    else:
        note_text = read_text_safe(session_note_path)
        if expected_command not in note_text:
            errors.append("session note does not contain the expected recovery command")
        if cwd and normalize_cwd(cwd) not in note_text:
            errors.append("session note does not contain the original working directory")

    daily_text = read_text_safe(daily_path)
    daily_lines = daily_text.splitlines(keepends=True)
    bounds = _sessions_block_bounds(daily_lines)
    if bounds is None:
        errors.append("daily note has no # Sessions block")
        return errors
    header_idx, end_idx = bounds
    body = daily_lines[header_idx + 1 : end_idx]
    registrations = [line for line in body if session_id in line]
    if len(registrations) != 1:
        errors.append(f"expected one daily registration for {session_id}, found {len(registrations)}")
    elif expected_command not in registrations[0]:
        errors.append("daily registration does not contain the expected recovery command")
    elif f"[[{session_note_path.stem}]]" not in registrations[0]:
        errors.append("daily registration does not link the selected session note")
    if any(_is_sessions_scaffold(line) for line in body):
        errors.append("daily # Sessions still contains template scaffold")
    return errors


def main() -> int:
    args = parse_args()
    runtime = args.runtime or detect_runtime()
    brain_root = Path(args.brain_root).expanduser().resolve()
    if not brain_root.is_dir():
        print(f"ERROR: vault root not found: {brain_root}", file=sys.stderr)
        return 1
    model_status = current_brain_status(brain_root)
    if model_status != "ok":
        print(
            "ERROR: brain root is not attached to the current agent-brain model "
            f"(status: {model_status}; expected: {current_model_root()}): {brain_root}",
            file=sys.stderr,
        )
        return 2

    mode = "apply" if args.apply else "dry-run"
    today = datetime.now().strftime("%Y-%m-%d")
    topic = derive_topic(args.session_label, args.cwd, brain_root)
    slug = f"{today}-session-{args.session_id}-{topic}"
    session_note_rel = Path("WIP") / "SESSIONS" / f"{slug}.md"
    session_note_path = brain_root / session_note_rel

    journal_folder = load_journal_folder(brain_root)
    journal_root = brain_root / journal_folder
    daily_notes = list_daily_notes(journal_root)
    latest_daily = daily_notes[-1].name if daily_notes else "NONE"
    today_path = journal_root / f"{today}.md"
    today_exists = today_path.exists()
    day_rollover = latest_daily != "NONE" and not today_exists

    sessions = list_session_notes(brain_root)
    open_sessions = [s for s in sessions if is_session_open(s)]

    wip_path = brain_root / "WIP" / "WIP.md"
    task_types_path = brain_root / "TASK_TYPES" / "TASK_TYPES.md"
    agents_md = brain_root / "AGENTS.md"
    brain_md = brain_root / "BRAIN.md"

    wip_context = extract_wip_context(wip_path, args.cwd)
    task_types = extract_task_types(task_types_path)
    template_path = find_template(brain_root)

    # Check for an existing session note from a prior day (same session ID, different date).
    # If found, reuse it rather than creating a duplicate today-dated note.
    existing_note = find_existing_session_note(brain_root, args.session_id)
    if existing_note and existing_note == session_note_path:
        # Same path = today-dated note already exists; not a cross-day continuation.
        existing_note = None
    if existing_note:
        effective_note_rel = existing_note.relative_to(brain_root)
        effective_slug = existing_note.stem
    else:
        effective_note_rel = session_note_rel
        effective_slug = slug

    # ── Compact digest ──────────────────────────────────────────────────────────
    print("# Session open digest")
    print(f"mode: {mode}")
    print(f"brain_root: {brain_root}")
    print(f"today: {today}")
    print(f"today_daily_exists: {'yes' if today_exists else 'no'}")
    print(f"latest_daily: {latest_daily}")
    print(f"day_rollover_detected: {'yes — run day-rollover protocol before work' if day_rollover else 'no'}")
    print(f"session_id: {args.session_id}")
    print(
        f"runtime: {runtime}  "
        f"(resume: {resume_command(runtime, args.session_id, args.cwd)})"
    )
    print(f"topic: {topic}")
    if existing_note:
        note_action = "continuing (prior day)"
    elif session_note_path.exists():
        note_action = "already exists"
    else:
        note_action = "creating" if args.apply else "would-create"
    print(f"session_note: {effective_note_rel}  ({note_action})")
    if not today_exists and args.prepare_daily:
        daily_action = "preparing + upserting" if args.apply else "would-prepare + upsert"
    elif today_exists:
        daily_action = "upserting" if args.apply else "would-upsert"
    else:
        daily_action = "missing — registration deferred"
    print(f"daily_update: {journal_folder}/{today}.md  ({daily_action})")
    print()

    print("open_sessions:")
    if open_sessions:
        for s in open_sessions:
            print(f"- {s.relative_to(brain_root)}")
    else:
        print("- none")
    print()

    print("operational_files:")
    for label, path in [("AGENTS.md", agents_md), ("BRAIN.md", brain_md), ("WIP/WIP.md", wip_path), ("TASK_TYPES/TASK_TYPES.md", task_types_path)]:
        print(f"- {label}: {'present' if path.exists() else 'missing'}")
    print()

    if wip_context:
        print("wip_context:")
        for line in wip_context:
            print(f"  {line}" if not line.startswith("  ") else line)
        print()

    if task_types:
        print("task_types:")
        for line in task_types:
            print(f"  {line}")
        print()

    # ── Apply: create session note + update daily ───────────────────────────────
    sessions_entry = build_sessions_entry(
        args.session_id,
        topic,
        effective_slug,
        runtime,
        args.cwd,
    )

    if args.apply:
        if args.prepare_daily:
            try:
                daily_prepare_action = prepare_daily_note(
                    brain_root,
                    today_path,
                    today,
                    apply=True,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
            if daily_prepare_action == "missing-template":
                print("ERROR: daily note template not found — daily not created.", file=sys.stderr)
                return 1
            print(f"daily_prepare: {daily_prepare_action}: {journal_folder}/{today}.md")
            today_exists = today_path.exists()
            navigation_errors = validate_daily_navigation(
                journal_root,
                today_path,
                today,
            )
            if navigation_errors:
                print("DAILY NAVIGATION POSTCONDITION FAILED:", file=sys.stderr)
                for error in navigation_errors:
                    print(f"  - {error}", file=sys.stderr)
                return 1
            print("daily_navigation: OK")

        if existing_note:
            recovery_action = upsert_session_recovery(
                brain_root / effective_note_rel,
                args.session_id,
                runtime,
                args.cwd,
                apply=True,
            )
            print(
                f"session note already exists (prior day): {effective_note_rel} "
                f"(recovery {recovery_action})"
            )
        elif session_note_path.exists():
            recovery_action = upsert_session_recovery(
                session_note_path,
                args.session_id,
                runtime,
                args.cwd,
                apply=True,
            )
            print(
                f"session note already exists: {session_note_rel} "
                f"(recovery {recovery_action})"
            )
        elif template_path:
            content = instantiate_session_template(
                template_path,
                today,
                topic,
                args.session_id,
                runtime,
                args.cwd,
            )
            session_note_path.parent.mkdir(parents=True, exist_ok=True)
            session_note_path.write_text(content, encoding="utf-8")
            print(f"created: {session_note_rel}")
        else:
            print("ERROR: session note template not found — session note not created.", file=sys.stderr)
            return 1

        if today_exists:
            daily_registration = upsert_sessions_entry(
                today_path,
                sessions_entry,
                args.session_id,
                apply=True,
            )
            if daily_registration in ("missing-daily", "missing-header"):
                print(
                    f"ERROR: session registration failed ({daily_registration}) in "
                    f"{journal_folder}/{today}.md.",
                    file=sys.stderr,
                )
                print(f"  Add manually: {sessions_entry}")
                return 1
            else:
                print(
                    f"daily_registration: {daily_registration}: "
                    f"{journal_folder}/{today}.md"
                )

                effective_note_path = brain_root / effective_note_rel
                postcondition_errors = validate_session_postconditions(
                    today_path,
                    effective_note_path,
                    args.session_id,
                    runtime,
                    args.cwd,
                )
                if postcondition_errors:
                    print("POSTCONDITION FAILED:", file=sys.stderr)
                    for error in postcondition_errors:
                        print(f"  - {error}", file=sys.stderr)
                    return 1
                print("postconditions: OK")
        else:
            print(f"NOTE: today's daily note is missing ({journal_folder}/{today}.md).")
            print(
                "  Complete the day-rollover review, then re-run with "
                "--prepare-daily --apply."
            )
            print(f"  Entry to add under # Sessions: {sessions_entry}")
    else:
        if existing_note:
            print(f"session note already exists (prior day), would skip creation: {effective_note_rel}")
        else:
            print(f"would-create: {session_note_rel}")
        if today_exists or args.prepare_daily:
            if not today_exists:
                try:
                    daily_prepare_action = prepare_daily_note(
                        brain_root,
                        today_path,
                        today,
                        apply=False,
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    print(f"ERROR: {exc}", file=sys.stderr)
                    return 1
                if daily_prepare_action == "missing-template":
                    print("ERROR: daily note template not found.", file=sys.stderr)
                    return 1
                print(f"daily_prepare: {daily_prepare_action}: {journal_folder}/{today}.md")
            print(f"would-upsert in: {journal_folder}/{today}.md")
            print(f"  entry: {sessions_entry}")
        else:
            print(f"NOTE: today's daily ({journal_folder}/{today}.md) is missing — # Sessions append deferred.")
            print(
                "  Complete the day-rollover review, then pass --prepare-daily "
                "with --apply."
            )
            print(f"  Entry to upsert after creating today's daily: {sessions_entry}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

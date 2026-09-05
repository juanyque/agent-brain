from __future__ import annotations

import os
import re
from pathlib import Path

from session_digest import normalize_cwd, resume_command
from session_open_discovery import read_text_safe
from session_open_fs import _open_regular_no_follow


SESSIONS_HEADER_RE = re.compile(r"^# Sessions\s*$")
SESSION_SCAFFOLD_PREFIXES = (
    "- REPLACE WITH REAL SESSION_ID",
    "- Example (OpenCode):",
    "- Example (Claude Code):",
    "- Example (Codex):",
)
SESSION_NOTE_REFERENCE_RE = re.compile(r"Session note:\s*\[\[[^\]]+\]\]\.?")
REOPENABLE_STATUS_RE = re.compile(
    r"^-\s*Status:\s*(?P<status>consolidated|stale-follow-up)\s*$",
    re.MULTILINE,
)


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
    return re.sub(
        r"## Resume command\n.*?(?=\n## |\Z)",
        resume_block + "\n",
        text,
        flags=re.DOTALL,
    )


def upsert_session_recovery(
    note_path: Path,
    session_id: str,
    runtime: str,
    cwd: str,
    apply: bool,
    *,
    safe_root: Path | None = None,
) -> str:
    """Make an existing session note's recovery block canonical and idempotent."""
    descriptor = -1
    stream = None
    try:
        if apply:
            descriptor = _open_regular_no_follow(note_path, os.O_RDWR, safe_root)
            stream = os.fdopen(descriptor, "r+", encoding="utf-8")
            descriptor = -1
            text = stream.read()
        else:
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
        if stream is not None:
            stream.seek(0)
            stream.write(new_text)
            stream.truncate()
        return "updated"
    finally:
        if stream is not None:
            stream.close()
        if descriptor >= 0:
            os.close(descriptor)


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
    for index, line in enumerate(lines):
        if SESSIONS_HEADER_RE.match(line.rstrip("\r\n")):
            header_idx = index
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


def apply_reopen_transition(
    note_path: Path,
    today: str,
    safe_root: Path | None = None,
) -> str:
    """Flip a consolidated/stale-follow-up Status to open with a dated Reopened line."""
    descriptor = _open_regular_no_follow(note_path, os.O_RDWR, safe_root)
    stream = os.fdopen(descriptor, "r+", encoding="utf-8")
    descriptor = -1
    try:
        text = stream.read()
        match = REOPENABLE_STATUS_RE.search(text)
        if match is None:
            return "not-consolidated"
        replacement = f"- Status: open\n- Reopened: {today} (from {match.group('status')})"
        new_text = REOPENABLE_STATUS_RE.sub(replacement, text, count=1)
        stream.seek(0)
        stream.write(new_text)
        stream.truncate()
        return "reopened"
    finally:
        stream.close()
        if descriptor >= 0:
            os.close(descriptor)


def upsert_sessions_entry(
    daily_path: Path,
    entry: str,
    session_id: str,
    apply: bool,
    *,
    safe_root: Path | None = None,
) -> str:
    """Ensure exactly one canonical registration for session_id."""
    descriptor = -1
    stream = None
    try:
        if apply:
            descriptor = _open_regular_no_follow(daily_path, os.O_RDWR, safe_root)
            stream = os.fdopen(descriptor, "r+", encoding="utf-8")
            descriptor = -1
            text = stream.read()
        else:
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
        new_text = "".join(
            lines[: header_idx + 1] + cleaned + lines[end_idx:]
        )
        changed = new_text != text
        if stream is not None and changed:
            stream.seek(0)
            stream.write(new_text)
            stream.truncate()
        if found == 0:
            return "added"
        if changed or found > 1 or scaffold_removed:
            return "updated"
        return "unchanged"
    finally:
        if stream is not None:
            stream.close()
        if descriptor >= 0:
            os.close(descriptor)

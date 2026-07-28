from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from session_digest import normalize_cwd, resume_command
from session_open_discovery import find_daily_neighbors
from session_open_fs import _read_daily_text, _read_optional_daily_text
from session_open_navigation import daily_navigation_targets
from session_open_registration import (
    _is_sessions_scaffold,
    _sessions_block_bounds,
)


def validate_daily_navigation(
    journal_root: Path,
    daily_path: Path,
    day: str,
) -> list[str]:
    """Return violations in the daily note's reciprocal navigation chain."""
    errors: list[str] = []
    try:
        previous_path, next_path = find_daily_neighbors(
            journal_root,
            daily_path,
            day,
        )
        previous_target, next_target = daily_navigation_targets(
            _read_daily_text(daily_path, journal_root)
        )
    except (OSError, ValueError) as exc:
        return [f"daily navigation could not be validated: {exc}"]
    current = date.fromisoformat(day)
    expected_previous = (
        previous_path.stem
        if previous_path
        else str(current - timedelta(days=1))
    )
    expected_next = (
        next_path.stem if next_path else str(current + timedelta(days=1))
    )
    if previous_target != expected_previous:
        errors.append(
            f"daily previous link is {previous_target}, expected {expected_previous}"
        )
    if next_target != expected_next:
        errors.append(
            f"daily next link is {next_target}, expected {expected_next}"
        )
    if previous_path is not None:
        try:
            _, previous_next = daily_navigation_targets(
                _read_daily_text(previous_path, journal_root)
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
                _read_daily_text(next_path, journal_root)
            )
            if next_previous != day:
                errors.append(
                    f"next daily {next_path.name} points previous to "
                    f"{next_previous}, expected {day}"
                )
        except (OSError, ValueError) as exc:
            errors.append(
                f"next daily navigation could not be validated: {exc}"
            )
    return errors


def validate_session_postconditions(
    daily_path: Path,
    session_note_path: Path,
    session_id: str,
    runtime: str,
    cwd: str,
    brain_root: Path | None = None,
) -> list[str]:
    """Return invariant violations after a session-open apply."""
    errors: list[str] = []
    expected_command = resume_command(runtime, session_id, cwd)
    safe_root = brain_root or Path(
        os.path.commonpath((daily_path.absolute(), session_note_path.absolute()))
    )
    try:
        note_text = _read_optional_daily_text(session_note_path, safe_root)
    except (OSError, ValueError) as exc:
        errors.append(f"session note could not be validated: {exc}")
        note_text = None
    if note_text is None:
        errors.append(f"session note missing: {session_note_path}")
    else:
        if expected_command not in note_text:
            errors.append(
                "session note does not contain the expected recovery command"
            )
        if cwd and normalize_cwd(cwd) not in note_text:
            errors.append(
                "session note does not contain the original working directory"
            )
    try:
        daily_lines = _read_daily_text(daily_path, safe_root).splitlines(keepends=True)
    except (OSError, ValueError) as exc:
        errors.append(f"daily note could not be validated: {exc}")
        return errors
    bounds = _sessions_block_bounds(daily_lines)
    if bounds is None:
        errors.append("daily note has no # Sessions block")
        return errors
    header_idx, end_idx = bounds
    body = daily_lines[header_idx + 1 : end_idx]
    registrations = [line for line in body if session_id in line]
    if len(registrations) != 1:
        errors.append(
            f"expected one daily registration for {session_id}, "
            f"found {len(registrations)}"
        )
    elif expected_command not in registrations[0]:
        errors.append(
            "daily registration does not contain the expected recovery command"
        )
    elif f"[[{session_note_path.stem}]]" not in registrations[0]:
        errors.append(
            "daily registration does not link the selected session note"
        )
    if any(_is_sessions_scaffold(line) for line in body):
        errors.append("daily # Sessions still contains template scaffold")
    return errors

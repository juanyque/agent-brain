from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from session_open_discovery import read_text_safe
from session_open_registration import (
    _is_sessions_scaffold,
    _sessions_block_bounds,
)


DAILY_NAVIGATION_RE = re.compile(
    r"^(?P<prefix>\s*\[\[)"
    r"(?P<previous>\d{4}-\d{2}-\d{2})"
    r"(?P<middle>\]\][^\[\r\n]*\[\[)"
    r"(?P<next>\d{4}-\d{2}-\d{2})"
    r"(?P<suffix>\]\][^\[\r\n]*)"
    r"(?P<newline>\r?\n?)$"
)


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
    text = text.replace(
        "<% tp.date.yesterday() %>",
        str(current - timedelta(days=1)),
    )
    text = text.replace(
        "<% tp.date.tomorrow() %>",
        str(current + timedelta(days=1)),
    )
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
    body = [
        line
        for line in lines[header_idx + 1 : end_idx]
        if not _is_sessions_scaffold(line)
    ]
    return "".join(lines[: header_idx + 1] + body + lines[end_idx:])

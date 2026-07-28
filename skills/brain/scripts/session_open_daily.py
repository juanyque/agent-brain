from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

from session_open_discovery import (
    find_daily_neighbors,
    find_daily_template,
    load_journal_folder,
)
from session_open_fs import (
    _read_daily_text,
    _read_optional_daily_text,
    _safe_write_scope,
    _unlink_daily_no_follow,
)
from session_open_navigation import (
    instantiate_daily_template,
    rewrite_daily_navigation,
)


class WriteTextHook(Protocol):
    def __call__(self, path: Path, content: str) -> None: ...


def _apply_daily_updates(
    updates: list[tuple[Path, str | None, str]],
    safe_root: Path,
    write_text: WriteTextHook,
) -> None:
    """Apply precomputed daily-note updates and restore originals on failure."""
    written: list[tuple[Path, str | None]] = []
    try:
        for path, original, content in updates:
            current = _read_optional_daily_text(path, safe_root)
            if current != original:
                raise RuntimeError(f"daily note changed before write: {path}")
            if current == content:
                continue
            written.append((path, original))
            write_text(path, content)
    except (OSError, RuntimeError) as exc:
        rollback_errors: list[str] = []
        for path, original in reversed(written):
            try:
                if original is None:
                    _unlink_daily_no_follow(path, safe_root)
                else:
                    write_text(path, original)
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
    write_text: WriteTextHook,
) -> str:
    """Create today's daily deterministically; never overwrite an existing note."""
    if _read_optional_daily_text(daily_path, brain_root) is not None:
        return "unchanged"
    template = find_daily_template(brain_root)
    if template is None:
        return "missing-template"
    journal_root = brain_root / load_journal_folder(brain_root)
    previous_path, next_path = find_daily_neighbors(journal_root, daily_path, day)
    current = date.fromisoformat(day)
    previous_day = (
        previous_path.stem
        if previous_path
        else str(current - timedelta(days=1))
    )
    next_day = (
        next_path.stem if next_path else str(current + timedelta(days=1))
    )
    content = instantiate_daily_template(
        template,
        day,
        previous_day=previous_day,
        next_day=next_day,
    )
    updates: list[tuple[Path, str | None, str]] = [
        (daily_path, None, content)
    ]
    if previous_path is not None:
        previous_content = _read_daily_text(previous_path, brain_root)
        updates.append(
            (
                previous_path,
                previous_content,
                rewrite_daily_navigation(previous_content, next_day=day),
            )
        )
    if next_path is not None:
        next_content = _read_daily_text(next_path, brain_root)
        updates.append(
            (
                next_path,
                next_content,
                rewrite_daily_navigation(next_content, previous_day=day),
            )
        )
    if apply:
        for path, original, _ in updates:
            if _read_optional_daily_text(path, brain_root) != original:
                raise RuntimeError(f"daily note changed before write: {path}")
        with _safe_write_scope(brain_root):
            _apply_daily_updates(updates, brain_root, write_text)
    return "created" if apply else "would-create"

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from session_open_fs import (
    _create_session_note_no_follow,
    _open_regular_no_follow,
    _restore_regular_file_no_follow,
    _rollback_created_session_note,
)
from session_open_registration import apply_reopen_transition, upsert_session_recovery
from session_open_validation import validate_session_postconditions


class TransactionHooks(Protocol):
    def instantiate_session_template(
        self,
        template_path: Path,
        date: str,
        topic: str,
        session_id: str,
        runtime: str,
        cwd: str,
    ) -> str: ...

    def upsert_sessions_entry(
        self,
        daily_path: Path,
        entry: str,
        session_id: str,
        apply: bool,
        *,
        safe_root: Path | None = None,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class SessionTransactionRequest:
    brain_root: Path
    today_path: Path
    today_exists: bool
    journal_folder: str
    today: str
    session_id: str
    runtime: str
    cwd: str
    topic: str
    session_note_rel: Path
    session_note_path: Path
    effective_note_rel: Path
    existing_note: Path | None
    template_path: Path | None
    sessions_entry: str
    reopen_status: str | None = None


def _read_bytes_no_follow(path: Path, safe_root: Path) -> bytes:
    descriptor = _open_regular_no_follow(path, os.O_RDONLY, safe_root)
    with os.fdopen(descriptor, "rb") as stream:
        return stream.read()


def apply_session_transaction(
    request: SessionTransactionRequest,
    hooks: TransactionHooks,
) -> int:
    created_parents: list[Path] = []
    created_session_note = False
    session_restore_path: Path | None = None
    session_original: bytes | None = None
    daily_original = (
        _read_bytes_no_follow(request.today_path, request.brain_root)
        if request.today_exists
        else None
    )
    daily_write_started = False
    transaction_committed = False
    try:
        if request.existing_note:
            session_restore_path = request.brain_root / request.effective_note_rel
            session_original = _read_bytes_no_follow(
                session_restore_path,
                request.brain_root,
            )
            if request.reopen_status is not None:
                reopen_action = apply_reopen_transition(
                    session_restore_path,
                    request.today,
                    safe_root=request.brain_root,
                )
                print(
                    f"reopened: {request.effective_note_rel} "
                    f"(Status: {request.reopen_status} -> open, "
                    f"Reopened: {request.today}; {reopen_action})"
                )
            recovery_action = upsert_session_recovery(
                session_restore_path,
                request.session_id,
                request.runtime,
                request.cwd,
                apply=True,
                safe_root=request.brain_root,
            )
            print(
                "session note already exists (prior day): "
                f"{request.effective_note_rel} (recovery {recovery_action})"
            )
        elif request.session_note_path.exists():
            session_restore_path = request.session_note_path
            session_original = _read_bytes_no_follow(
                session_restore_path,
                request.brain_root,
            )
            recovery_action = upsert_session_recovery(
                request.session_note_path,
                request.session_id,
                request.runtime,
                request.cwd,
                apply=True,
                safe_root=request.brain_root,
            )
            print(
                f"session note already exists: {request.session_note_rel} "
                f"(recovery {recovery_action})"
            )
        elif request.template_path:
            content = hooks.instantiate_session_template(
                request.template_path,
                request.today,
                request.topic,
                request.session_id,
                request.runtime,
                request.cwd,
            )
            try:
                created_parents = _create_session_note_no_follow(
                    request.brain_root,
                    request.session_note_path,
                    content,
                )
            except OSError as exc:
                print(
                    f"ERROR: session note could not be created safely: {exc}",
                    file=sys.stderr,
                )
                return 1
            created_session_note = True
            print(f"created: {request.session_note_rel}")
        else:
            print(
                "ERROR: session note template not found — session note not created.",
                file=sys.stderr,
            )
            return 1
        if request.today_exists:
            try:
                daily_write_started = True
                daily_registration = hooks.upsert_sessions_entry(
                    request.today_path,
                    request.sessions_entry,
                    request.session_id,
                    apply=True,
                    safe_root=request.brain_root,
                )
            except OSError as exc:
                print(
                    f"ERROR: session registration write failed: {exc}",
                    file=sys.stderr,
                )
                return 1
            if daily_registration in ("missing-daily", "missing-header"):
                print(
                    "ERROR: session registration failed "
                    f"({daily_registration}) in "
                    f"{request.journal_folder}/{request.today}.md.",
                    file=sys.stderr,
                )
                print(f"  Add manually: {request.sessions_entry}")
                return 1
            print(
                f"daily_registration: {daily_registration}: "
                f"{request.journal_folder}/{request.today}.md"
            )
            postcondition_errors = validate_session_postconditions(
                request.today_path,
                request.brain_root / request.effective_note_rel,
                request.session_id,
                request.runtime,
                request.cwd,
                request.brain_root,
            )
            if postcondition_errors:
                print("POSTCONDITION FAILED:", file=sys.stderr)
                for error in postcondition_errors:
                    print(f"  - {error}", file=sys.stderr)
                return 1
            print("postconditions: OK")
        else:
            print(
                "NOTE: today's daily note is missing "
                f"({request.journal_folder}/{request.today}.md)."
            )
            print(
                "  Complete the day-rollover review, then re-run with "
                "--prepare-daily --apply."
            )
            print(f"  Entry to add under # Sessions: {request.sessions_entry}")
        transaction_committed = True
        return 0
    finally:
        if not transaction_committed:
            rollback_errors: list[str] = []
            if daily_write_started and daily_original is not None:
                daily_error = _restore_regular_file_no_follow(
                    request.today_path,
                    daily_original,
                    request.brain_root,
                )
                if daily_error is not None:
                    rollback_errors.append(daily_error)
            if created_session_note:
                rollback_errors.extend(
                    _rollback_created_session_note(
                        request.brain_root,
                        request.session_note_path,
                        created_parents,
                    )
                )
            elif session_restore_path is not None and session_original is not None:
                session_error = _restore_regular_file_no_follow(
                    session_restore_path,
                    session_original,
                    request.brain_root,
                )
                if session_error is not None:
                    rollback_errors.append(session_error)
            if rollback_errors:
                print(
                    "ERROR: session-open rollback was incomplete: "
                    + "; ".join(rollback_errors),
                    file=sys.stderr,
                )

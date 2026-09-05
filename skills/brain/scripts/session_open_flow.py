from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from brain_state import current_brain_status, current_model_root
from model_check_no_follow import lstat_entry, symlinked_parent
from session_digest import SessionDigestRequest, render_session_digest
from session_open_context import collect_session_digest_state, derive_topic
from session_open_discovery import JournalConfigError, find_existing_session_note, find_template, list_daily_notes, load_journal_folder, read_session_status
from session_open_registration import build_sessions_entry
from session_open_transaction import SessionTransactionRequest, apply_session_transaction
from session_open_validation import validate_daily_navigation

class InstantiateSessionHook(Protocol):
    def __call__(self, template_path: Path, date: str, topic: str, session_id: str, runtime: str, cwd: str) -> str: ...


class UpsertSessionsHook(Protocol):
    def __call__(self, daily_path: Path, entry: str, session_id: str, apply: bool, *, safe_root: Path | None = None) -> str: ...


class PrepareDailyHook(Protocol):
    def __call__(self, brain_root: Path, daily_path: Path, day: str, apply: bool) -> str: ...


@dataclass(frozen=True, slots=True)
class SessionOpenHooks:
    instantiate_session_template: InstantiateSessionHook
    upsert_sessions_entry: UpsertSessionsHook
    prepare_daily_note: PrepareDailyHook


@dataclass(frozen=True, slots=True)
class SessionOpenRequest:
    brain_root: str
    session_id: str
    runtime: str
    session_label: str
    cwd: str
    prepare_daily: bool
    apply: bool
    reopen_consolidated: bool = False


def run_flow(request: SessionOpenRequest, hooks: SessionOpenHooks) -> int:
    brain_root = Path(request.brain_root).expanduser().resolve()
    if not brain_root.is_dir():
        print(f"ERROR: vault root not found: {brain_root}", file=sys.stderr)
        return 1
    model_status = current_brain_status(brain_root)
    if model_status != "ok":
        message = "ERROR: brain root is not attached to the current agent-brain model "
        print(message + f"(status: {model_status}; expected: {current_model_root()}): {brain_root}", file=sys.stderr)
        return 2
    today = datetime.now().strftime("%Y-%m-%d")
    topic = derive_topic(request.session_label, request.cwd, brain_root)
    slug = f"{today}-session-{request.session_id}-{topic}"
    session_note_rel = Path("WIP") / "SESSIONS" / f"{slug}.md"
    session_note_path = brain_root / session_note_rel
    if request.apply:
        unsafe_parent = symlinked_parent(brain_root, session_note_path)
        if unsafe_parent is not None:
            print(f"ERROR: session note parent is a symlink: {unsafe_parent}", file=sys.stderr)
            return 1
        if lstat_entry(session_note_path).is_symlink:
            print(f"ERROR: session note destination is a symlink: {session_note_path}", file=sys.stderr)
            return 1
    try:
        journal_folder = load_journal_folder(brain_root)
    except JournalConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    journal_root = brain_root / journal_folder
    daily_notes = list_daily_notes(journal_root)
    latest_daily = daily_notes[-1].name if daily_notes else "NONE"
    today_path = journal_root / f"{today}.md"
    if request.apply:
        unsafe_parent = symlinked_parent(brain_root, today_path)
        if unsafe_parent is not None:
            print(f"ERROR: daily note parent is a symlink: {unsafe_parent}", file=sys.stderr)
            return 1
        if lstat_entry(today_path).is_symlink:
            print(f"ERROR: daily note destination is a symlink: {today_path}", file=sys.stderr)
            return 1
    today_exists = today_path.exists()
    template_path = find_template(brain_root)
    existing_note = find_existing_session_note(brain_root, request.session_id)
    if existing_note and existing_note == session_note_path:
        existing_note = None
    reopen_status: str | None = None
    consolidated_conflict: str | None = None
    if existing_note is not None:
        existing_status = read_session_status(existing_note)
        if existing_status in ("consolidated", "stale-follow-up"):
            if request.reopen_consolidated:
                reopen_status = existing_status
            elif request.apply:
                print(
                    f"ERROR: session note is {existing_status} — refusing to register it "
                    f"as active: {existing_note.relative_to(brain_root)}",
                    file=sys.stderr,
                )
                print(
                    "  Continue in a NEW session id, or re-run with --reopen-consolidated "
                    "to record an explicit reopen (Status → open with a Reopened line).",
                    file=sys.stderr,
                )
                return 1
            else:
                consolidated_conflict = existing_status
    if existing_note:
        effective_note_rel = existing_note.relative_to(brain_root)
        effective_slug = existing_note.stem
    else:
        effective_note_rel = session_note_rel
        effective_slug = slug
    try:
        digest_state = collect_session_digest_state(
            SessionDigestRequest(
                brain_root=str(brain_root),
                session_id=request.session_id,
                runtime=request.runtime,
                session_label=request.session_label,
                cwd=request.cwd,
                prepare_daily=request.prepare_daily,
                apply=request.apply,
                today=today,
            )
        )
    except JournalConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(render_session_digest(digest_state))
    if consolidated_conflict is not None:
        print(
            f"consolidated_note: session note Status is {consolidated_conflict} — apply "
            "refuses; continue in a NEW session id or pass --reopen-consolidated to "
            "record an explicit reopen."
        )
    sessions_entry = build_sessions_entry(
        request.session_id,
        topic,
        effective_slug,
        request.runtime,
        request.cwd,
    )
    if request.apply:
        if request.prepare_daily:
            try:
                daily_prepare_action = hooks.prepare_daily_note(
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
        if today_exists:
            daily_registration = hooks.upsert_sessions_entry(
                today_path,
                sessions_entry,
                request.session_id,
                apply=False,
            )
            if daily_registration in ("missing-daily", "missing-header"):
                print(
                    "ERROR: session registration failed "
                    f"({daily_registration}) in "
                    f"{journal_folder}/{today}.md.",
                    file=sys.stderr,
                )
                print(f"  Add manually: {sessions_entry}")
                return 1
        return apply_session_transaction(
            SessionTransactionRequest(
                brain_root=brain_root,
                today_path=today_path,
                today_exists=today_exists,
                journal_folder=journal_folder,
                today=today,
                session_id=request.session_id,
                runtime=request.runtime,
                cwd=request.cwd,
                topic=topic,
                session_note_rel=session_note_rel,
                session_note_path=session_note_path,
                effective_note_rel=effective_note_rel,
                existing_note=existing_note,
                template_path=template_path,
                sessions_entry=sessions_entry,
                reopen_status=reopen_status,
            ),
            hooks,
        )
    if existing_note:
        print(
            "session note already exists (prior day), would skip creation: "
            f"{effective_note_rel}"
        )
    else:
        print(f"would-create: {session_note_rel}")
    if today_exists or request.prepare_daily:
        if not today_exists:
            try:
                daily_prepare_action = hooks.prepare_daily_note(
                    brain_root,
                    today_path,
                    today,
                    apply=False,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
            if daily_prepare_action == "missing-template":
                print(
                    "ERROR: daily note template not found.",
                    file=sys.stderr,
                )
                return 1
            print(
                f"daily_prepare: {daily_prepare_action}: "
                f"{journal_folder}/{today}.md"
            )
        print(f"would-upsert in: {journal_folder}/{today}.md")
        print(f"  entry: {sessions_entry}")
    else:
        print(
            f"NOTE: today's daily ({journal_folder}/{today}.md) is missing "
            "— # Sessions append deferred."
        )
        print(
            "  Complete the day-rollover review, then pass --prepare-daily "
            "with --apply."
        )
        print(
            "  Entry to upsert after creating today's daily: "
            f"{sessions_entry}"
        )
    return 0

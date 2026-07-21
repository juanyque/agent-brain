#!/usr/bin/env python3
"""Read-only postcondition checker for session and WIP brain writes."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from session_open import (
    find_existing_session_note,
    load_journal_folder,
    normalize_cwd,
    read_text_safe,
    resume_command,
    validate_session_postconditions,
)


WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]*)?\)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify deterministic postconditions after brain session/WIP writes."
    )
    parser.add_argument("--brain-root", required=True, help="Brain root path.")
    parser.add_argument("--session-id", help="Runtime session ID to verify.")
    parser.add_argument(
        "--runtime",
        choices=["claude", "opencode", "codex", "generic"],
        help="Runtime used to build the expected recovery command.",
    )
    parser.add_argument("--cwd", default="", help="Original session working directory.")
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Daily date containing the session registration (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--wip-note",
        action="append",
        default=[],
        help="Brain-relative active WIP note that must be registered in WIP/WIP.md. "
        "Repeat for multiple notes.",
    )
    return parser.parse_args()


def dashboard_links(text: str) -> set[str]:
    links = {match.group(1).strip() for match in WIKILINK_RE.finditer(text)}
    links.update(match.group(1).strip(" <>\t") for match in MARKDOWN_LINK_RE.finditer(text))
    return links


def validate_wip_registration(brain_root: Path, note_arg: str) -> list[str]:
    errors: list[str] = []
    brain_root = brain_root.expanduser().resolve()
    note_path = Path(note_arg).expanduser()
    if not note_path.is_absolute():
        note_path = brain_root / note_path
    try:
        note_path = note_path.resolve()
        note_path.relative_to(brain_root)
    except (OSError, ValueError):
        return [f"WIP note is outside the brain: {note_arg}"]
    if not note_path.exists():
        return [f"WIP note missing: {note_path}"]

    dashboard_path = brain_root / "WIP" / "WIP.md"
    if not dashboard_path.exists():
        return [f"WIP dashboard missing: {dashboard_path}"]
    try:
        rel_to_dashboard = note_path.relative_to(dashboard_path.parent)
    except ValueError:
        return [f"active WIP note is not under WIP/: {note_path.relative_to(brain_root)}"]
    links = dashboard_links(read_text_safe(dashboard_path))
    rel_to_brain = note_path.relative_to(brain_root)
    accepted = {
        note_path.stem,
        note_path.name,
        str(rel_to_brain),
        str(rel_to_brain.with_suffix("")),
        str(rel_to_dashboard),
        str(rel_to_dashboard.with_suffix("")),
    }
    if links.isdisjoint(accepted):
        errors.append(
            f"active WIP note is not registered in WIP/WIP.md: "
            f"{note_path.relative_to(brain_root)}"
        )
    return errors


def main() -> int:
    args = parse_args()
    brain_root = Path(args.brain_root).expanduser().resolve()
    if not brain_root.is_dir():
        print(f"ERROR: brain root not found: {brain_root}", file=sys.stderr)
        return 2
    if not args.session_id and not args.wip_note:
        print("ERROR: pass --session-id and/or --wip-note", file=sys.stderr)
        return 2
    if args.session_id and not args.runtime:
        print("ERROR: --runtime is required with --session-id", file=sys.stderr)
        return 2

    errors: list[str] = []
    if args.session_id:
        journal_folder = load_journal_folder(brain_root)
        daily_path = brain_root / journal_folder / f"{args.date}.md"
        note_path = find_existing_session_note(brain_root, args.session_id)
        if note_path is None:
            errors.append(f"session note not found for {args.session_id}")
        else:
            errors.extend(
                validate_session_postconditions(
                    daily_path,
                    note_path,
                    args.session_id,
                    args.runtime,
                    args.cwd,
                )
            )

    for note_arg in args.wip_note:
        errors.extend(validate_wip_registration(brain_root, note_arg))

    if errors:
        print("Brain postcondition check: FAILED")
        for error in errors:
            print(f"  FAIL {error}")
        return 1

    print("Brain postcondition check: OK")
    if args.session_id:
        print(
            f"  OK   session {args.session_id}: "
            f"{resume_command(args.runtime, args.session_id, args.cwd)}"
        )
        if args.cwd:
            print(f"  OK   working directory: {normalize_cwd(args.cwd)}")
    for note_arg in args.wip_note:
        print(f"  OK   WIP registered: {note_arg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

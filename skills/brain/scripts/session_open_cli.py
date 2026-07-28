from __future__ import annotations

import argparse
import os

from session_open_flow import SessionOpenHooks, SessionOpenRequest, run_flow


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
    if os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "claude"
    return "generic"


def main(hooks: SessionOpenHooks) -> int:
    args = parse_args()
    request = SessionOpenRequest(
        brain_root=args.brain_root,
        session_id=args.session_id,
        runtime=args.runtime or detect_runtime(),
        session_label=args.session_label,
        cwd=args.cwd,
        prepare_daily=args.prepare_daily,
        apply=args.apply,
    )
    return run_flow(request, hooks)

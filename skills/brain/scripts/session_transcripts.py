"""Best-effort evidence of whether a session did any work outside its note.

A session note can be empty because nothing happened or because the work
went through tool calls and external posts that never reached the note.
Claude Code keeps a per-session transcript, so for those sessions we can tell
the two apart; other runtimes have no transcript here and stay unverified.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# A bare brain open already costs a handful of tool calls; more than this
# means the session did something else.
ACTIVITY_TOOL_USE_THRESHOLD = 8
ACTIVITY_PROMPT_THRESHOLD = 2

UNVERIFIED = "unverified"
NO_ACTIVITY = "no-activity-evidence"
HAS_ACTIVITY = "has-activity"


def claude_projects_root() -> Path:
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(config).expanduser() if config else Path.home() / ".claude"
    return base / "projects"


def find_claude_transcript(session_id: str) -> Path | None:
    root = claude_projects_root()
    if not session_id or not root.is_dir():
        return None
    for path in root.glob(f"*/{session_id}.jsonl"):
        if path.is_file():
            return path
    return None


def _is_user_prompt(entry: dict) -> bool:
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(
            isinstance(block, dict) and block.get("type") == "text" for block in content
        )
    return False


def transcript_counts(path: Path) -> tuple[int, int]:
    """Return (user prompts, tool calls) found in a Claude transcript."""
    prompts = 0
    tool_uses = 0
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if _is_user_prompt(entry):
                prompts += 1
            elif entry.get("type") == "assistant":
                content = entry.get("message", {}).get("content")
                if isinstance(content, list):
                    tool_uses += sum(
                        1
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "tool_use"
                    )
    return prompts, tool_uses


def classify_session_activity(session_id: str) -> tuple[str, str]:
    """Return (verdict, detail). Only `no-activity-evidence` supports closing."""
    transcript = find_claude_transcript(session_id)
    if transcript is None:
        return UNVERIFIED, "no Claude transcript found"
    try:
        prompts, tool_uses = transcript_counts(transcript)
    except OSError as error:
        return UNVERIFIED, f"transcript unreadable: {error}"
    detail = f"{prompts} prompts, {tool_uses} tool calls"
    if tool_uses > ACTIVITY_TOOL_USE_THRESHOLD or prompts >= ACTIVITY_PROMPT_THRESHOLD:
        return HAS_ACTIVITY, detail
    return NO_ACTIVITY, detail

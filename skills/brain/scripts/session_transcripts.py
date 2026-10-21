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
from typing import NamedTuple

# A bare brain open already costs a handful of tool calls; more than this
# means the session did something else.
ACTIVITY_TOOL_USE_THRESHOLD = 8
ACTIVITY_PROMPT_THRESHOLD = 2
# Tools that change files or act outside the session count as work on their own,
# whatever the total number of calls.
OUTWARD_TOOL_NAMES = frozenset({"Edit", "Write", "NotebookEdit", "Agent", "Workflow", "SendMessage"})
OUTWARD_TOOL_PREFIX = "mcp__"
# A long assistant reply is work too, even in a session that made no tool calls.
ACTIVITY_TEXT_CHARS = 2000

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


class TranscriptCounts(NamedTuple):
    prompts: int
    tool_uses: int
    outward_tool_uses: int
    text_chars: int
    records: int


def _is_outward_tool(name: object) -> bool:
    return isinstance(name, str) and (
        name in OUTWARD_TOOL_NAMES or name.startswith(OUTWARD_TOOL_PREFIX)
    )


def transcript_counts(path: Path) -> TranscriptCounts:
    """Count prompts, tool calls and assistant text in a Claude transcript.

    `records` is the number of readable user/assistant entries; a file with none
    (empty, truncated, unknown schema) carries no evidence either way.
    """
    prompts = tool_uses = outward = text_chars = records = 0
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == "user":
                records += 1
                if _is_user_prompt(entry):
                    prompts += 1
            elif entry.get("type") == "assistant":
                records += 1
                content = entry.get("message", {}).get("content")
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_use":
                            tool_uses += 1
                            if _is_outward_tool(block.get("name")):
                                outward += 1
                        elif block.get("type") == "text":
                            text = block.get("text")
                            if isinstance(text, str):
                                text_chars += len(text)
    return TranscriptCounts(prompts, tool_uses, outward, text_chars, records)


def classify_session_activity(session_id: str) -> tuple[str, str]:
    """Return (verdict, detail). Only `no-activity-evidence` supports closing."""
    transcript = find_claude_transcript(session_id)
    if transcript is None:
        return UNVERIFIED, "no Claude transcript found"
    try:
        counts = transcript_counts(transcript)
    except OSError as error:
        return UNVERIFIED, f"transcript unreadable: {error}"
    if counts.records == 0:
        return UNVERIFIED, "transcript has no readable records"
    detail = (
        f"{counts.prompts} prompts, {counts.tool_uses} tool calls, "
        f"{counts.outward_tool_uses} outward, {counts.text_chars} reply chars"
    )
    if (
        counts.tool_uses > ACTIVITY_TOOL_USE_THRESHOLD
        or counts.prompts >= ACTIVITY_PROMPT_THRESHOLD
        or counts.outward_tool_uses > 0
        or counts.text_chars > ACTIVITY_TEXT_CHARS
    ):
        return HAS_ACTIVITY, detail
    return NO_ACTIVITY, detail

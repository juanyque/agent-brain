#!/usr/bin/env python3
"""Session-open ceremony script.

Single-script replacement for the ~15 Read/Bash calls that opening a vault session used to require.

1. Resolves vault state (daily notes, open sessions, warnings).
2. Reads context files and emits a compact digest (<30 lines).
3. (--apply) Creates the session note from TEMPLATE.wip-session.common.md.
4. (--apply) Appends the session entry to today's daily note # Sessions block.

Dry-run by default; pass --apply to write files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
SESSIONS_HEADER_RE = re.compile(r"^# Sessions\s*$")
HEADING_RE = re.compile(r"^#{1,3} ")
TASK_TYPE_ITEM_RE = re.compile(r"^- \[\[")
STATUS_RE = re.compile(r"^-\s+Status:\s*(.+)$")

TEMPLATE_CANDIDATES = [
    Path("TEMPLATES/TEMPLATE.wip-session.common.md"),
    Path("_COMMON/TEMPLATES/TEMPLATE.wip-session.common.md"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Session-open ceremony: resolve vault state, create session note, update daily."
    )
    parser.add_argument("--vault-root", required=True, help="Vault root path.")
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
        help="Current working directory for WIP context filtering.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write session note and update daily note. Default is dry-run.",
    )
    return parser.parse_args()


def detect_runtime() -> str:
    # Only Claude Code exposes a stable env var. OpenCode and others must be passed
    # explicitly via --runtime by the calling agent, which always knows its runtime.
    if os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "claude"
    return "generic"


def resume_command(runtime: str, session_id: str) -> str:
    r = (runtime or "").strip().lower()
    if r == "claude":
        return f"claude --resume {session_id}"
    if r == "opencode":
        return f"opencode -s {session_id}"
    if r == "codex":
        return f"codex resume {session_id}"
    # Never claim a wrong runtime: fall back to the bare id so the mistake is visible.
    return session_id


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def derive_topic(session_label: str, cwd: str, vault_root: Path) -> str:
    if session_label:
        slug = slugify(session_label)
        if slug:
            return slug
    if cwd:
        slug = slugify(Path(cwd).name)
        if slug:
            return slug
    slug = slugify(vault_root.name)
    if slug:
        return slug
    return f"unspecified-{datetime.now().strftime('%Y%m%d-%H%M')}"


def load_journal_folder(vault_root: Path) -> str:
    config_path = vault_root / ".obsidian" / "daily-notes.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            return cfg.get("folder", "JOURNAL")
        except Exception:
            pass
    return "JOURNAL"


def list_daily_notes(journal_root: Path) -> list[Path]:
    notes = []
    for p in journal_root.rglob("*.md"):
        if DATE_RE.match(p.name):
            notes.append(p)
    return sorted(notes)


def list_session_notes(vault_root: Path) -> list[Path]:
    session_dir = vault_root / "WIP" / "SESSIONS"
    if not session_dir.exists():
        return []
    return sorted(session_dir.glob("*.md"))


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def read_lines_safe(path: Path) -> list[str]:
    return read_text_safe(path).splitlines()


def find_template(vault_root: Path) -> Path | None:
    for candidate in TEMPLATE_CANDIDATES:
        path = vault_root / candidate
        if path.exists():
            return path
    return None


def is_session_open(note_path: Path) -> bool:
    for line in read_lines_safe(note_path):
        m = STATUS_RE.match(line.strip())
        if m:
            return m.group(1).strip().lower() == "open"
    return False


def _read_status(path: Path) -> str:
    for line in read_lines_safe(path):
        m = STATUS_RE.match(line.strip())
        if m:
            return m.group(1).strip().lower()
    return ""


def find_existing_session_note(vault_root: Path, session_id: str) -> Path | None:
    """Return the most recent active session note for session_id, regardless of date prefix.

    Used by --apply to avoid creating a duplicate when the same session continues
    across a day boundary. Returns the most recent open/handoff-only note, or None
    if no prior note exists for this session ID.
    """
    session_dir = vault_root / "WIP" / "SESSIONS"
    if not session_dir.exists():
        return None
    matches = [p for p in session_dir.glob("*.md") if session_id in p.name]
    if not matches:
        return None
    active = sorted(
        [p for p in matches if _read_status(p) in ("open", "handoff-only")],
        reverse=True,  # alphabetical desc = most-recent-first for date-prefixed names
    )
    return active[0] if active else sorted(matches, reverse=True)[0]


def extract_wip_context(wip_path: Path, cwd: str, max_headings: int = 5) -> list[str]:
    if not wip_path.exists():
        return []
    lines = read_lines_safe(wip_path)
    keywords: set[str] = set()
    if cwd:
        basename = Path(cwd).name.lower()
        keywords.add(basename)
        keywords.update(part for part in re.split(r"[-_/]", basename) if len(part) > 2)

    result: list[str] = []
    seen = 0
    i = 0
    n = len(lines)
    while i < n and seen < max_headings:
        line = lines[i]
        if HEADING_RE.match(line):
            relevant = (not keywords) or any(kw in line.lower() for kw in keywords)
            if relevant:
                result.append(line)
                seen += 1
                j = i + 1
                child_count = 0
                while j < n and child_count < 3 and not HEADING_RE.match(lines[j]):
                    if lines[j].strip():
                        result.append(f"  {lines[j]}")
                        child_count += 1
                    j += 1
                i = j
                continue
        i += 1

    if not result and keywords:
        return extract_wip_context(wip_path, "", max_headings=3)
    return result


def extract_task_types(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in read_lines_safe(path) if TASK_TYPE_ITEM_RE.match(line)]


def instantiate_session_template(
    template_path: Path,
    date: str,
    topic: str,
    session_id: str,
    runtime: str,
) -> str:
    text = read_text_safe(template_path)
    text = text.replace(
        "# Session <date> / <topic> / <id>",
        f"# Session {date} / {topic} / {session_id}",
    )
    resume_block = f"## Resume command\n- `{resume_command(runtime, session_id)}`"
    text = re.sub(
        r"## Resume command\n.*?(?=\n## |\Z)",
        resume_block + "\n",
        text,
        flags=re.DOTALL,
    )
    return text


def build_sessions_entry(session_id: str, topic: str, slug: str, runtime: str) -> str:
    label = topic.replace("-", "/") if topic else session_id[:8]
    return f"- `{resume_command(runtime, session_id)}` — {label}. Session note: [[{slug}]]."


def append_to_sessions_block(daily_path: Path, entry: str, apply: bool) -> bool:
    text = read_text_safe(daily_path)
    if not text:
        return False
    lines = text.splitlines(keepends=True)
    header_idx = None
    for i, line in enumerate(lines):
        if SESSIONS_HEADER_RE.match(line.rstrip("\n")):
            header_idx = i
            break
    if header_idx is None:
        return False

    # Find end of # Sessions block (next top-level header, not # Sessions itself)
    j = header_idx + 1
    while j < len(lines):
        stripped = lines[j].rstrip("\n")
        if stripped.startswith("# ") and not SESSIONS_HEADER_RE.match(stripped):
            break
        j += 1
    # Walk back past trailing blank lines to insert after last real entry
    k = j - 1
    while k > header_idx and lines[k].strip() == "":
        k -= 1
    insert_idx = k + 1

    lines.insert(insert_idx, entry + "\n")
    if apply:
        daily_path.write_text("".join(lines), encoding="utf-8")
    return True


def main() -> int:
    args = parse_args()
    runtime = args.runtime or detect_runtime()
    vault_root = Path(args.vault_root).expanduser().resolve()
    if not vault_root.is_dir():
        print(f"ERROR: vault root not found: {vault_root}", file=sys.stderr)
        return 1

    mode = "apply" if args.apply else "dry-run"
    today = datetime.now().strftime("%Y-%m-%d")
    topic = derive_topic(args.session_label, args.cwd, vault_root)
    slug = f"{today}-session-{args.session_id}-{topic}"
    session_note_rel = Path("WIP") / "SESSIONS" / f"{slug}.md"
    session_note_path = vault_root / session_note_rel

    journal_folder = load_journal_folder(vault_root)
    journal_root = vault_root / journal_folder
    daily_notes = list_daily_notes(journal_root)
    latest_daily = daily_notes[-1].name if daily_notes else "NONE"
    today_path = journal_root / f"{today}.md"
    today_exists = today_path.exists()
    day_rollover = latest_daily != "NONE" and not today_exists

    sessions = list_session_notes(vault_root)
    open_sessions = [s for s in sessions if is_session_open(s)]

    wip_path = vault_root / "WIP" / "WIP.md"
    task_types_path = vault_root / "TASK_TYPES" / "TASK_TYPES.md"
    agents_md = vault_root / "AGENTS.md"
    brain_md = vault_root / "BRAIN.md"

    wip_context = extract_wip_context(wip_path, args.cwd)
    task_types = extract_task_types(task_types_path)
    template_path = find_template(vault_root)

    # Check for an existing session note from a prior day (same session ID, different date).
    # If found, reuse it rather than creating a duplicate today-dated note.
    existing_note = find_existing_session_note(vault_root, args.session_id)
    if existing_note and existing_note == session_note_path:
        # Same path = today-dated note already exists; not a cross-day continuation.
        existing_note = None
    if existing_note:
        effective_note_rel = existing_note.relative_to(vault_root)
        effective_slug = existing_note.stem
    else:
        effective_note_rel = session_note_rel
        effective_slug = slug

    # ── Compact digest ──────────────────────────────────────────────────────────
    print("# Session open digest")
    print(f"mode: {mode}")
    print(f"vault_root: {vault_root}")
    print(f"today: {today}")
    print(f"today_daily_exists: {'yes' if today_exists else 'no'}")
    print(f"latest_daily: {latest_daily}")
    print(f"day_rollover_detected: {'yes — run day-rollover protocol before work' if day_rollover else 'no'}")
    print(f"session_id: {args.session_id}")
    print(f"runtime: {runtime}  (resume: {resume_command(runtime, args.session_id)})")
    print(f"topic: {topic}")
    if existing_note:
        note_action = "continuing (prior day)"
    elif session_note_path.exists():
        note_action = "already exists"
    else:
        note_action = "creating" if args.apply else "would-create"
    print(f"session_note: {effective_note_rel}  ({note_action})")
    print(f"daily_update: {journal_folder}/{today}.md  ({'appending' if args.apply else 'would-append'})")
    print()

    print("open_sessions:")
    if open_sessions:
        for s in open_sessions:
            print(f"- {s.relative_to(vault_root)}")
    else:
        print("- none")
    print()

    print("operational_files:")
    for label, path in [("AGENTS.md", agents_md), ("BRAIN.md", brain_md), ("WIP/WIP.md", wip_path), ("TASK_TYPES/TASK_TYPES.md", task_types_path)]:
        print(f"- {label}: {'present' if path.exists() else 'missing'}")
    print()

    if wip_context:
        print("wip_context:")
        for line in wip_context:
            print(f"  {line}" if not line.startswith("  ") else line)
        print()

    if task_types:
        print("task_types:")
        for line in task_types:
            print(f"  {line}")
        print()

    # ── Apply: create session note + update daily ───────────────────────────────
    sessions_entry = build_sessions_entry(args.session_id, topic, effective_slug, runtime)

    if args.apply:
        if existing_note:
            print(f"session note already exists (prior day), skipping creation: {effective_note_rel}")
        elif session_note_path.exists():
            print(f"WARNING: session note already exists, skipping: {session_note_rel}")
        elif template_path:
            content = instantiate_session_template(template_path, today, topic, args.session_id, runtime)
            session_note_path.parent.mkdir(parents=True, exist_ok=True)
            session_note_path.write_text(content, encoding="utf-8")
            print(f"created: {session_note_rel}")
        else:
            print("ERROR: session note template not found — session note not created.", file=sys.stderr)
            return 1

        if today_exists:
            ok = append_to_sessions_block(today_path, sessions_entry, apply=True)
            if ok:
                print(f"updated: {journal_folder}/{today}.md  (appended to # Sessions)")
            else:
                print(f"WARNING: # Sessions block not found in {journal_folder}/{today}.md — entry not appended.", file=sys.stderr)
                print(f"  Add manually: {sessions_entry}")
        else:
            print(f"NOTE: today's daily note is missing ({journal_folder}/{today}.md).")
            print(f"  Create today's daily first (day-rollover protocol), then run --apply again.")
            print(f"  Entry to add under # Sessions: {sessions_entry}")
    else:
        if existing_note:
            print(f"session note already exists (prior day), would skip creation: {effective_note_rel}")
        else:
            print(f"would-create: {session_note_rel}")
        if today_exists:
            print(f"would-append to: {journal_folder}/{today}.md")
            print(f"  entry: {sessions_entry}")
        else:
            print(f"NOTE: today's daily ({journal_folder}/{today}.md) is missing — # Sessions append deferred.")
            print(f"  Entry to add after creating today's daily: {sessions_entry}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

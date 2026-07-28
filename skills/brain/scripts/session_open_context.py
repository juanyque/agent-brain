from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from session_digest import SessionDigestRequest, SessionDigestState
from session_open_discovery import (
    find_existing_session_note,
    is_session_open,
    list_daily_notes,
    list_session_notes,
    load_journal_folder,
    read_lines_safe,
)


HEADING_RE = re.compile(r"^#{1,3} ")
TASK_TYPE_ITEM_RE = re.compile(r"^- \[\[")


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def derive_topic(session_label: str, cwd: str, brain_root: Path) -> str:
    if session_label:
        slug = slugify(session_label)
        if slug:
            return slug
    if cwd:
        slug = slugify(Path(cwd).name)
        if slug:
            return slug
    slug = slugify(brain_root.name)
    if slug:
        return slug
    return f"unspecified-{datetime.now().strftime('%Y%m%d-%H%M')}"


def extract_wip_context(
    wip_path: Path,
    cwd: str,
    max_headings: int = 5,
) -> list[str]:
    if not wip_path.exists():
        return []
    lines = read_lines_safe(wip_path)
    cwd_basename = ""
    keywords: set[str] = set()
    if cwd:
        cwd_basename = Path(cwd).name.lower()
        keywords.update(
            part
            for part in re.split(r"[^a-z0-9]+", cwd_basename)
            if len(part) > 2 and part not in {"all", "and", "for", "the", "with"}
        )
    result: list[str] = []
    seen = 0
    index = 0
    while index < len(lines) and seen < max_headings:
        line = lines[index]
        if HEADING_RE.match(line):
            heading_lower = line.lower()
            heading_tokens = set(re.split(r"[^a-z0-9]+", heading_lower))
            relevant = (
                not keywords
                or cwd_basename in heading_lower
                or bool(keywords & heading_tokens)
            )
            if relevant:
                result.append(line)
                seen += 1
                child_index = index + 1
                child_count = 0
                while (
                    child_index < len(lines)
                    and child_count < 3
                    and not HEADING_RE.match(lines[child_index])
                ):
                    if lines[child_index].strip():
                        result.append(f"  {lines[child_index]}")
                        child_count += 1
                    child_index += 1
                index = child_index
                continue
        index += 1
    if not result and keywords:
        return extract_wip_context(wip_path, "", max_headings=3)
    return result


def extract_task_types(path: Path) -> list[str]:
    if not path.exists():
        return []
    task_types: list[str] = []
    seen: set[str] = set()
    for line in read_lines_safe(path):
        if not TASK_TYPE_ITEM_RE.match(line) or line in seen:
            continue
        task_types.append(line)
        seen.add(line)
    return task_types


def collect_session_digest_state(
    request: SessionDigestRequest,
) -> SessionDigestState:
    brain_root = Path(request.brain_root).expanduser().resolve()
    mode = "apply" if request.apply else "dry-run"
    today = request.today or datetime.now().strftime("%Y-%m-%d")
    topic = derive_topic(request.session_label, request.cwd, brain_root)
    slug = f"{today}-session-{request.session_id}-{topic}"
    session_note_rel = Path("WIP") / "SESSIONS" / f"{slug}.md"
    session_note_path = brain_root / session_note_rel
    fixture = request.fixture_data
    if fixture is None:
        journal_folder = load_journal_folder(brain_root)
        journal_root = brain_root / journal_folder
        daily_notes = list_daily_notes(journal_root)
        latest_daily = daily_notes[-1].name if daily_notes else "NONE"
        today_path = journal_root / f"{today}.md"
        today_exists = today_path.exists()
        open_sessions = tuple(
            str(session.relative_to(brain_root))
            for session in list_session_notes(brain_root)
            if is_session_open(session)
        )
        wip_path = brain_root / "WIP" / "WIP.md"
        task_types_path = brain_root / "TASK_TYPES" / "TASK_TYPES.md"
        operational_files = (
            ("AGENTS.md", (brain_root / "AGENTS.md").exists()),
            ("BRAIN.md", (brain_root / "BRAIN.md").exists()),
            ("WIP/WIP.md", wip_path.exists()),
            ("TASK_TYPES/TASK_TYPES.md", task_types_path.exists()),
        )
        wip_context = tuple(extract_wip_context(wip_path, request.cwd))
        task_types = tuple(extract_task_types(task_types_path))
        existing_note = find_existing_session_note(brain_root, request.session_id)
        session_note_exists = session_note_path.exists()
        injected_project_agents = False
    else:
        journal_folder = fixture.journal_folder
        latest_daily = fixture.daily_notes[-1] if fixture.daily_notes else "NONE"
        today_exists = fixture.today_daily_exists
        open_sessions = fixture.open_sessions
        operational_files = fixture.operational_files
        wip_context = fixture.wip_context
        task_types = fixture.task_types
        existing_note = (
            brain_root / fixture.existing_session_note
            if fixture.existing_session_note is not None
            else None
        )
        session_note_exists = fixture.session_note_exists
        injected_project_agents = fixture.injected_project_agents
    day_rollover = latest_daily != "NONE" and not today_exists
    if existing_note is not None and existing_note == session_note_path:
        existing_note = None
    if existing_note:
        effective_note_rel = existing_note.relative_to(brain_root)
        note_action = "continuing (prior day)"
    else:
        effective_note_rel = session_note_rel
        if session_note_exists:
            note_action = "already exists"
        else:
            note_action = "creating" if request.apply else "would-create"
    if not today_exists and request.prepare_daily:
        daily_action = (
            "preparing + upserting" if request.apply else "would-prepare + upsert"
        )
    elif today_exists:
        daily_action = "upserting" if request.apply else "would-upsert"
    else:
        daily_action = "missing — registration deferred"
    return SessionDigestState(
        mode=mode,
        brain_root=str(brain_root),
        today=today,
        today_daily_exists=today_exists,
        latest_daily=latest_daily,
        day_rollover_detected=day_rollover,
        session_id=request.session_id,
        runtime=request.runtime,
        cwd=request.cwd,
        topic=topic,
        session_note=effective_note_rel.as_posix(),
        note_action=note_action,
        daily_update=f"{journal_folder}/{today}.md",
        daily_action=daily_action,
        open_sessions=open_sessions,
        operational_files=operational_files,
        wip_context=wip_context,
        task_types=task_types,
        injected_project_agents=injected_project_agents,
    )

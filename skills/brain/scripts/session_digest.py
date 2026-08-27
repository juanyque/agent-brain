from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Final


RESUME_COMMAND_TEMPLATES: Final = {
    "antigravity": "agy --conversation {session_id}",
    "claude": "claude --resume {session_id}",
    "codex": "codex resume {session_id}",
    "opencode": "opencode -s {session_id}",
}


@dataclass(frozen=True, slots=True)
class SessionDigestFixtureData:
    journal_folder: str
    daily_notes: tuple[str, ...]
    today_daily_exists: bool
    session_note_exists: bool
    existing_session_note: str | None
    open_sessions: tuple[str, ...]
    operational_files: tuple[tuple[str, bool], ...]
    wip_context: tuple[str, ...]
    task_types: tuple[str, ...]
    maintenance_jobs: tuple[str, ...]
    sources_due: tuple[str, ...]
    injected_project_agents: bool


@dataclass(frozen=True, slots=True)
class SessionDigestState:
    mode: str
    brain_root: str
    today: str
    today_daily_exists: bool
    latest_daily: str
    day_rollover_detected: bool
    session_id: str
    runtime: str
    cwd: str
    topic: str
    session_note: str
    note_action: str
    daily_update: str
    daily_action: str
    open_sessions: tuple[str, ...]
    operational_files: tuple[tuple[str, bool], ...]
    wip_context: tuple[str, ...]
    task_types: tuple[str, ...]
    maintenance_jobs: tuple[str, ...]
    sources_due: tuple[str, ...]
    injected_project_agents: bool


@dataclass(frozen=True, slots=True)
class SessionDigestRequest:
    brain_root: str
    session_id: str
    runtime: str
    session_label: str
    cwd: str
    prepare_daily: bool
    apply: bool
    today: str | None = None
    fixture_data: SessionDigestFixtureData | None = None


def normalize_cwd(cwd: str) -> str:
    path = Path(cwd).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return str(path)


def resume_command(runtime: str, session_id: str, cwd: str = "") -> str:
    r = (runtime or "").strip().lower()
    template = RESUME_COMMAND_TEMPLATES.get(r)
    if template is None:
        return session_id
    command = template.format(session_id=session_id)
    if cwd:
        return f"cd {shlex.quote(normalize_cwd(cwd))} && {command}"
    return command


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def render_session_digest(state: SessionDigestState) -> str:
    lines = [
        "# Session open digest",
        f"mode: {state.mode}",
        f"brain_root: {state.brain_root}",
        f"today: {state.today}",
        f"today_daily_exists: {_yes_no(state.today_daily_exists)}",
        f"latest_daily: {state.latest_daily}",
        "day_rollover_detected: "
        + (
            "yes — run day-rollover protocol before work"
            if state.day_rollover_detected
            else "no"
        ),
        f"session_id: {state.session_id}",
        (
            f"runtime: {state.runtime}  "
            f"(resume: {resume_command(state.runtime, state.session_id, state.cwd)})"
        ),
        f"topic: {state.topic}",
        f"session_note: {state.session_note}  ({state.note_action})",
        f"daily_update: {state.daily_update}  ({state.daily_action})",
    ]
    if state.injected_project_agents:
        lines.append("project_agents_injected: yes")
    lines.extend(["", "open_sessions:"])
    if state.open_sessions:
        lines.extend(f"- {session}" for session in state.open_sessions)
    else:
        lines.append("- none")
    lines.extend(["", "operational_files:"])
    lines.extend(
        f"- {label}: {'present' if exists else 'missing'}"
        for label, exists in state.operational_files
    )
    lines.append("")
    if state.wip_context:
        lines.append("wip_context:")
        lines.extend(
            f"  {line}" if not line.startswith("  ") else line
            for line in state.wip_context
        )
        lines.append("")
    if state.task_types:
        lines.append("task_types:")
        lines.extend(f"  {line}" for line in state.task_types)
        lines.append("")
    if state.maintenance_jobs:
        lines.append("maintenance_jobs:")
        lines.extend(f"  {line}" for line in state.maintenance_jobs)
        lines.append("")
    if state.sources_due:
        lines.append("sources_due:")
        lines.extend(f"  {line}" for line in state.sources_due)
        lines.append("")
    return "\n".join(lines) + "\n"


def fixed_session_digest_fixture_data() -> SessionDigestFixtureData:
    return SessionDigestFixtureData(
        journal_folder="JOURNAL",
        daily_notes=("2000-01-02.md",),
        today_daily_exists=True,
        session_note_exists=False,
        existing_session_note=None,
        open_sessions=("WIP/SESSIONS/1999-12-31-session-previous.md",),
        operational_files=(
            ("AGENTS.md", True),
            ("BRAIN.md", True),
            ("WIP/WIP.md", True),
            ("TASK_TYPES/TASK_TYPES.md", True),
        ),
        wip_context=(
            "## Fixture project",
            "  - fixed WIP context for /fixture/project",
        ),
        task_types=("- [[fixture-task]] Fixed task route",),
        maintenance_jobs=("- Weekly: due (No Weekly job entry found for the current ISO week.)",),
        sources_due=("- fixture-source (messaging-tool): never checked",),
        injected_project_agents=True,
    )


def fixed_session_digest_request() -> SessionDigestRequest:
    return SessionDigestRequest(
        brain_root="/fixture/brain",
        session_id="fixture-session",
        runtime="codex",
        session_label="fixture-session",
        cwd="/fixture/project",
        prepare_daily=False,
        apply=False,
        today="2000-01-02",
        fixture_data=fixed_session_digest_fixture_data(),
    )

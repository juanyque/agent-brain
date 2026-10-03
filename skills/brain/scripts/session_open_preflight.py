from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionPreflight:
    """Cheap advisory signals for sessions that may share state."""

    git_root: str | None = None
    branch: str | None = None
    changed_entries: int = 0
    git_status_available: bool = True
    git_unavailable: bool = False
    peer_sessions: int = 0
    rollover_pending: bool = False


def _git_metadata(cwd: str) -> tuple[str | None, str | None]:
    if not cwd:
        return None, None
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel", "--abbrev-ref", "HEAD"],
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    if result.returncode != 0:
        return None, None
    lines = result.stdout.splitlines()
    if len(lines) < 2:
        return None, None
    return lines[0], lines[1] or "(detached HEAD)"


def _git_changed_entries(cwd: str) -> tuple[int, bool]:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain=v1", "-z", "-uall"],
            capture_output=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return 0, False
    if result.returncode != 0:
        return 0, False
    return sum(1 for entry in result.stdout.split(b"\0") if entry), True


def collect_preflight(
    *,
    cwd: str,
    session_id: str,
    open_sessions: tuple[str, ...],
    rollover_pending: bool,
) -> SessionPreflight:
    git_root, branch = _git_metadata(cwd)
    changed_entries, git_status_available = (
        _git_changed_entries(cwd) if git_root else (0, True)
    )
    current_marker = f"session-{session_id}-"
    peer_sessions = sum(1 for session in open_sessions if current_marker not in session)
    return SessionPreflight(
        git_root=git_root,
        branch=branch,
        changed_entries=changed_entries,
        git_status_available=git_status_available,
        git_unavailable=bool(cwd) and git_root is None,
        peer_sessions=peer_sessions,
        rollover_pending=rollover_pending,
    )

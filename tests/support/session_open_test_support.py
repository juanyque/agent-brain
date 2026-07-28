from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "brain" / "scripts"
MODEL_ROOT = Path(__file__).resolve().parents[2] / "model"
sys.path.insert(0, str(SCRIPTS_DIR))

import session_open  # noqa: E402
from session_open import (  # noqa: E402
    build_sessions_entry,
    daily_navigation_targets,
    extract_wip_context,
    find_daily_template,
    instantiate_daily_template,
    instantiate_session_template,
    list_daily_notes,
    prepare_daily_note,
    resume_command,
    upsert_sessions_entry,
    validate_daily_navigation,
    validate_session_postconditions,
)


def snapshot_tree(root: Path) -> list[tuple[str, str, bytes]]:
    entries: list[tuple[str, str, bytes]] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((rel, "symlink", os.readlink(path).encode()))
        elif path.is_file():
            entries.append((rel, "file", path.read_bytes()))
        elif path.is_dir():
            entries.append((rel, "dir", b""))
    return entries


def attach_current_model(brain: Path) -> None:
    (brain / "_COMMON").symlink_to(MODEL_ROOT, target_is_directory=True)

#!/usr/bin/env python3
"""Brain state machine — authoritative state detection (D21/D24).

Shared by home_setup, runtime_manager, and bootstrap. Consulted before any
mutation to decide the correct flow for the brain's current state.

States:
  virgin                 — no _COMMON + no markers (wrappers). Fresh folder.
  attached-link-missing   — markers present + _COMMON missing/broken (cloned
                           brain where _COMMON is gitignored per D3/D24).
  initial                — _COMMON ok + _STAGING with content (being reorganized).
  maintenance            — _COMMON ok + no _STAGING (organized, stable).
  conflict               — _COMMON points to a different model (D25: ask switch).
"""

from __future__ import annotations

import os
from pathlib import Path

COMMON_LINK_NAME = "_COMMON"
STAGING_DIR_NAME = "_STAGING"
AGENTS_DIR_NAME = "_AGENTS"
OPERATIONAL_TOP_LEVEL_DIRS = {COMMON_LINK_NAME, STAGING_DIR_NAME, AGENTS_DIR_NAME}

MARKERS = ["AGENTS.md", "VAULT.md", "JOBS.md"]


def relative_symlink_target(source: Path, link_path: Path) -> str:
    return os.path.relpath(source.resolve(), start=link_path.parent.resolve())


def link_status(brain_root: Path, common_target: Path) -> tuple[str, str]:
    """Return (status, desired_relative_target) for the _COMMON symlink.

    status is one of: missing, conflict-not-symlink, ok, conflict-wrong-target
    """
    link_path = brain_root / COMMON_LINK_NAME
    desired = relative_symlink_target(common_target, link_path)

    if not link_path.exists() and not link_path.is_symlink():
        return "missing", desired
    if not link_path.is_symlink():
        return "conflict-not-symlink", desired
    if link_path.resolve() == common_target.resolve():
        return "ok", desired
    return "conflict-wrong-target", desired


def staging_status(brain_root: Path) -> tuple[str, int]:
    """Return (status, item_count) for _STAGING in the brain root.

    status is one of: missing, empty, has-content
    """
    staging = brain_root / STAGING_DIR_NAME
    if not staging.is_dir():
        return "missing", 0
    items = [p for p in staging.iterdir() if p.name != ".git"]
    return ("empty" if not items else "has-content"), len(items)


def has_markers(brain_root: Path) -> bool:
    """Check if wrapper marker files exist at the brain root (D24).

    Markers are wrapper files (AGENTS.md, VAULT.md, etc.) that survive a
    git clone even when _COMMON (gitignored) does not. Their presence
    distinguishes 'attached-link-missing' from 'virgin'.
    """
    return any((brain_root / marker).exists() for marker in MARKERS)


def detect_state(brain_root: Path, common_target: Path) -> str:
    """Determine the authoritative brain state.

    Returns one of: virgin, attached-link-missing, initial, maintenance, conflict
    """
    link_st, _ = link_status(brain_root, common_target)

    if link_st == "ok":
        staging_st, _ = staging_status(brain_root)
        if staging_st == "has-content":
            return "initial"
        return "maintenance"

    if link_st == "missing":
        if has_markers(brain_root):
            return "attached-link-missing"
        return "virgin"

    return "conflict"

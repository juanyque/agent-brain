#!/usr/bin/env python3
"""Find agent-brain HOME candidates (notes-agnostic).

A HOME is a folder the operating model can attach to. Each candidate is classified by
notes_mode: 'obsidian' (has .obsidian/), 'generic' (looks like a notes folder), or
'empty'. Reuses find_vaults.py for Obsidian detection so the two stay consistent.

Usage:
    python3 find_home.py                  # search from home directory
    python3 find_home.py /path/to/search  # search under a root
    python3 find_home.py /path/to/check   # classify a single path (any mode, incl. empty)

Exit codes:
    0 - candidate(s) found (search mode), or path classified (single-path mode)
    1 - no candidates found, or path does not exist

Output: JSON {search_root, provided_path, homes:[{path,name,notes_mode,has_agents_md,has_common}], count}.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from find_vaults import SKIP_DIRS, is_vault

GENERIC_MIN_MD = 5
OP_DIRS = {"JOURNAL", "MEMORY", "WIP", "_AGENTS", "BACKLOG", "INBOX"}


def _count_md(path: Path) -> int:
    try:
        return sum(1 for p in path.iterdir() if p.suffix == ".md")
    except (PermissionError, OSError):
        return 0


def _has_op_dirs(path: Path) -> bool:
    try:
        return any((path / d).is_dir() for d in OP_DIRS)
    except (PermissionError, OSError):
        return False


def classify(path: Path) -> str:
    if is_vault(path):
        return "obsidian"
    if (path / "todo.txt").is_file() or _has_op_dirs(path):
        return "generic"
    if (path / "README.md").is_file() and _count_md(path) >= 3:
        return "generic"
    if _count_md(path) >= GENERIC_MIN_MD:
        return "generic"
    return "empty"


def home_info(path: Path) -> dict:
    return {
        "path": str(path),
        "name": path.name,
        "notes_mode": classify(path),
        "has_agents_md": (path / "AGENTS.md").is_file(),
        "has_common": (path / "_COMMON").exists(),
    }


def find_homes_under(root: Path, max_depth: int = 4) -> list[dict]:
    result: list[dict] = []
    visited: set[Path] = set()

    def _walk(current: Path, depth: int) -> None:
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            return
        if classify(current) in ("obsidian", "generic"):
            result.append(home_info(current))
        if depth >= max_depth:
            return
        for entry in entries:
            if not entry.is_dir():
                continue
            if entry.name in SKIP_DIRS or entry.name.startswith("."):
                continue
            real = entry.resolve()
            if real in visited:
                continue
            visited.add(real)
            _walk(entry, depth + 1)

    visited.add(root.resolve())
    _walk(root, 0)
    return sorted(result, key=lambda h: h["path"])


def main() -> int:
    provided = len(sys.argv) > 1
    if provided:
        target = Path(sys.argv[1].strip()).expanduser().resolve()
        if not target.exists():
            print(json.dumps({
                "search_root": str(target),
                "provided_path": True,
                "homes": [],
                "count": 0,
                "error": f"Path does not exist: {target}",
            }))
            return 1
        info = home_info(target)
        print(json.dumps({
            "search_root": str(target),
            "provided_path": True,
            "homes": [info],
            "count": 1,
        }))
        return 0

    homes = find_homes_under(Path.home())
    print(json.dumps({
        "search_root": str(Path.home()),
        "provided_path": False,
        "homes": homes,
        "count": len(homes),
    }))
    return 0 if homes else 1


if __name__ == "__main__":
    raise SystemExit(main())

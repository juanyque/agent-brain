#!/usr/bin/env python3
"""Find agent-brain candidates (notes-agnostic).

A brain is a folder the operating model can attach to. Each candidate is classified by
notes_mode: 'obsidian' (has .obsidian/), 'generic' (looks like a notes folder), or
'empty'. This is the single discovery script (absorbed find_vaults.py).

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

SKIP_DIRS = {
    ".git", "node_modules", ".Trash", ".cache", ".Trash-0",
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", ".next", ".nuxt", "dist", "build", ".gradle",
    "Library", "Applications", ".local", ".npm", ".nvm", ".cargo",
    ".rustup", ".docker", ".kube",
}


def is_vault(path: Path) -> bool:
    return (path / ".obsidian").is_dir()

GENERIC_MIN_MD = 5
OP_DIRS = {"journal", "memory", "wip", "_agents", "backlog", "inbox"}
MARKER_NAMES = {"todo.txt", "todo.md", "wip.txt", "wip.md"}


def _iter_filenames(path: Path) -> list[str]:
    try:
        return [p.name.lower() for p in path.iterdir() if p.is_file()]
    except (PermissionError, OSError):
        return []


def _iter_dirnames(path: Path) -> list[str]:
    try:
        return [p.name.lower() for p in path.iterdir() if p.is_dir()]
    except (PermissionError, OSError):
        return []


def _has_op_dirs(path: Path) -> bool:
    return any(d in OP_DIRS for d in _iter_dirnames(path))


def _count_md(path: Path) -> int:
    return sum(1 for n in _iter_filenames(path) if n.endswith(".md"))


def classify(path: Path) -> str:
    if is_vault(path):
        return "obsidian"
    names = _iter_filenames(path)
    has_marker = any(n in MARKER_NAMES for n in names)
    has_readme = "readme.md" in names
    if has_marker or _has_op_dirs(path):
        return "generic"
    if has_readme and _count_md(path) >= 3:
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

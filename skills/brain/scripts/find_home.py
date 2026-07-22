#!/usr/bin/env python3
"""Find brains implanted with the current agent-brain model.

Default discovery accepts only roots whose _COMMON symlink resolves to the model
directory belonging to this checkout. Broad notes-folder heuristics remain available
only through --candidates for bootstrap destination suggestions.

Usage:
    python3 find_home.py                    # search for implanted brains under HOME
    python3 find_home.py /path/inside/brain # resolve the nearest implanted ancestor
    python3 find_home.py --candidates       # bootstrap destination suggestions
    python3 find_home.py --candidates PATH  # classify one bootstrap destination

Exit codes:
    0 - implanted brain(s) or bootstrap candidate(s) found
    1 - no matching result, or path does not exist

Output is JSON. In default mode, homes contains only current-model brains and
conflicts describes encountered _COMMON entries that are not valid implants.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_SCRIPTS = REPO_ROOT / "model" / "SCRIPTS"
if str(MODEL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MODEL_SCRIPTS))

from brain_state import current_brain_status, current_model_root  # noqa: E402

SKIP_DIRS = {
    ".git", "node_modules", ".Trash", ".cache", ".Trash-0",
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", ".next", ".nuxt", "dist", "build", ".gradle",
    "Library", "Applications", ".local", ".npm", ".nvm", ".cargo",
    ".rustup", ".docker", ".kube",
    "_COMMON", "_STAGING", "_AGENTS",
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


def candidate_info(path: Path) -> dict:
    return {
        "path": str(path.resolve()),
        "name": path.name,
        "notes_mode": classify(path),
        "has_agents_md": (path / "AGENTS.md").is_file(),
        "has_common": (path / "_COMMON").exists() or (path / "_COMMON").is_symlink(),
    }


def brain_info(path: Path) -> dict:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "name": resolved.name,
        "model_status": "ok",
        "has_agents_md": (resolved / "AGENTS.md").is_file(),
        "has_brain_md": (resolved / "BRAIN.md").is_file(),
        "is_nested": False,
        "parent_brain": None,
    }


def conflict_info(path: Path, status: str) -> dict:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "name": resolved.name,
        "model_status": status,
    }


def _mark_nested(homes: list[dict]) -> None:
    paths = {Path(home["path"]) for home in homes}
    for home in homes:
        path = Path(home["path"])
        ancestors = [candidate for candidate in paths if candidate != path and candidate in path.parents]
        if ancestors:
            parent = max(ancestors, key=lambda candidate: len(candidate.parts))
            home["is_nested"] = True
            home["parent_brain"] = str(parent)


def find_implanted_under(
    root: Path,
    max_depth: int = 4,
) -> tuple[list[dict], list[dict]]:
    result: list[dict] = []
    conflicts: list[dict] = []
    visited: set[Path] = set()

    def _walk(current: Path, depth: int) -> None:
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            return
        status = current_brain_status(current)
        if status == "ok":
            result.append(brain_info(current))
        elif status != "missing":
            conflicts.append(conflict_info(current, status))
        if depth >= max_depth:
            return
        for entry in entries:
            if entry.is_symlink() or not entry.is_dir():
                continue
            if (
                entry.name in SKIP_DIRS
                or entry.name.startswith(".")
                or entry.name.startswith("_COMMON.backup-")
            ):
                continue
            real = entry.resolve()
            if real in visited:
                continue
            visited.add(real)
            _walk(entry, depth + 1)

    visited.add(root.resolve())
    _walk(root, 0)
    result = sorted({home["path"]: home for home in result}.values(), key=lambda h: h["path"])
    conflicts = sorted(
        {item["path"]: item for item in conflicts}.values(),
        key=lambda item: item["path"],
    )
    _mark_nested(result)
    return result, conflicts


def find_candidates_under(root: Path, max_depth: int = 4) -> list[dict]:
    result: list[dict] = []
    visited: set[Path] = {root.resolve()}

    def _walk(current: Path, depth: int) -> None:
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            return
        if classify(current) in ("obsidian", "generic"):
            result.append(candidate_info(current))
        if depth >= max_depth:
            return
        for entry in entries:
            if entry.is_symlink() or not entry.is_dir():
                continue
            if (
                entry.name in SKIP_DIRS
                or entry.name.startswith(".")
                or entry.name.startswith("_COMMON.backup-")
            ):
                continue
            real = entry.resolve()
            if real in visited:
                continue
            visited.add(real)
            _walk(entry, depth + 1)

    _walk(root, 0)
    return sorted(
        {candidate["path"]: candidate for candidate in result}.values(),
        key=lambda candidate: candidate["path"],
    )


def nearest_implanted_ancestor(target: Path) -> tuple[list[dict], list[dict]]:
    for current in (target, *target.parents):
        status = current_brain_status(current)
        if status == "ok":
            return [brain_info(current)], []
        if status != "missing":
            return [], [conflict_info(current, status)]
    return [], []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find current-model brains, or bootstrap candidates with --candidates."
    )
    parser.add_argument(
        "--candidates",
        action="store_true",
        help="Use broad notes-folder heuristics for bootstrap destination suggestions.",
    )
    parser.add_argument("path", nargs="?", help="Path to validate or resolve from.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    provided = args.path is not None
    if provided:
        target = Path(args.path.strip()).expanduser().resolve()
        if not target.exists():
            print(json.dumps({
                "search_root": str(target),
                "provided_path": True,
                "mode": "candidates" if args.candidates else "implanted",
                "expected_model_root": str(current_model_root()),
                "homes": [],
                "conflicts": [],
                "count": 0,
                "error": f"Path does not exist: {target}",
            }))
            return 1
        if args.candidates:
            homes = [candidate_info(target)]
            conflicts: list[dict] = []
        else:
            homes, conflicts = nearest_implanted_ancestor(target)
        print(json.dumps({
            "search_root": str(target),
            "provided_path": True,
            "mode": "candidates" if args.candidates else "implanted",
            "expected_model_root": str(current_model_root()),
            "homes": homes,
            "conflicts": conflicts,
            "count": len(homes),
        }))
        return 0 if homes else 1

    root = Path.home().resolve()
    if args.candidates:
        homes = find_candidates_under(root)
        conflicts = []
    else:
        homes, conflicts = find_implanted_under(root)
    print(json.dumps({
        "search_root": str(root),
        "provided_path": False,
        "mode": "candidates" if args.candidates else "implanted",
        "expected_model_root": str(current_model_root()),
        "homes": homes,
        "conflicts": conflicts,
        "count": len(homes),
    }))
    return 0 if homes else 1


if __name__ == "__main__":
    raise SystemExit(main())

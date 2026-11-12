#!/usr/bin/env python3
"""Find brains implanted with the current agent-brain model.

Default discovery accepts only roots whose _COMMON symlink resolves to the model
directory belonging to this checkout. Broad notes-folder heuristics remain available
only through --candidates for bootstrap destination suggestions.

Usage:
    python3 find_home.py                    # search for implanted brains under HOME
    python3 find_home.py PATH               # resolve a brain for PATH (see below)
    python3 find_home.py --no-scan PATH     # same, but never scan HOME (fast; for hooks)
    python3 find_home.py --all PATH         # ignore the default; list every brain
                                            # reachable from PATH's tree, its ancestors and HOME
    python3 find_home.py --candidates       # bootstrap destination suggestions
    python3 find_home.py --candidates PATH  # classify one bootstrap destination

Resolution for PATH, in order (the first that applies wins):
    1. ancestor  - PATH is inside an implanted brain.
    2. conflict  - the nearest ancestor with a _COMMON entry is not a valid
                   implant: stop, never fall back (needs repair/migration).
    3. default   - this machine's default brain (see brain_default.py), if usable.
    4. home-scan - exactly one implanted brain under HOME. More than one is
                   "ambiguous": they are listed in `candidates`, none is selected.

Exit codes:
    0 - a brain was resolved (or, without PATH / with --all / --candidates,
        implanted brain(s) or bootstrap candidate(s) were found)
    1 - nothing resolved (none, ambiguous, conflict), or path does not exist

Output is JSON. In default mode, homes contains only current-model brains and
conflicts describes encountered _COMMON entries that are not valid implants.
With PATH, `status` is resolved|ambiguous|conflict|none and `source` says how a
resolved brain was found (ancestor|default|home-scan).
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

from brain_state import current_brain_status, current_model_root, is_linked_worktree  # noqa: E402
from default_brain import read_default  # noqa: E402

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


def repair_hint(path: Path, status: str) -> str | None:
    """How to fix a dangling `_COMMON`, which is the only conflict with a lightweight repair."""
    if status != "conflict-invalid-target":
        return None
    script = current_model_root() / "SCRIPTS" / "home_setup.py"
    command = f"python3 {script} --brain {path} --relink-common"
    cause = (
        "this brain is a linked git worktree and _COMMON is a relative symlink that does not "
        "resolve at this depth"
        if is_linked_worktree(path)
        else "_COMMON is a symlink whose target does not exist"
    )
    return (
        f"{cause}; preview with `{command}`, then repoint only _COMMON with "
        f"`{command} --apply`"
    )


def conflict_info(path: Path, status: str) -> dict:
    resolved = path.resolve()
    info = {
        "path": str(resolved),
        "name": resolved.name,
        "model_status": status,
    }
    hint = repair_hint(resolved, status)
    if hint is not None:
        info["hint"] = hint
    return info


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


def _dedupe(homes: list[dict]) -> list[dict]:
    merged = sorted({home["path"]: home for home in homes}.values(), key=lambda h: h["path"])
    for home in merged:
        home["is_nested"] = False
        home["parent_brain"] = None
    _mark_nested(merged)
    return merged


def resolve_from_path(target: Path, scan_home: bool) -> tuple[dict, bool]:
    """Resolve a brain for `target`. Returns (payload fields, resolved)."""
    homes, conflicts = nearest_implanted_ancestor(target)
    if homes:
        return {"status": "resolved", "source": "ancestor", "homes": homes, "conflicts": []}, True
    if conflicts:
        # A conflicting _COMMON nearer than any valid brain must never be bypassed.
        return {"status": "conflict", "source": None, "homes": [], "conflicts": conflicts}, False

    extra: dict = {}
    default = read_default()
    if default.status == "ok" and default.brain is not None:
        return {
            "status": "resolved",
            "source": "default",
            "homes": [brain_info(default.brain)],
            "conflicts": [],
        }, True
    if default.status == "invalid":
        extra["default_problem"] = default.reason

    if scan_home:
        found, found_conflicts = find_implanted_under(Path.home().resolve())
        if len(found) == 1:
            return {
                "status": "resolved", "source": "home-scan", "homes": found,
                "conflicts": found_conflicts, **extra,
            }, True
        if len(found) > 1:
            return {
                "status": "ambiguous", "source": None, "homes": [],
                "candidates": found, "conflicts": found_conflicts, **extra,
            }, False
    return {"status": "none", "source": None, "homes": [], "conflicts": [], **extra}, False


def search_all(target: Path) -> tuple[list[dict], list[dict]]:
    """Every brain reachable from `target`'s ancestors, its subtree and HOME (deduplicated)."""
    ancestor_homes, ancestor_conflicts = nearest_implanted_ancestor(target)
    tree_homes, tree_conflicts = find_implanted_under(target)
    home_homes, home_conflicts = find_implanted_under(Path.home().resolve())
    homes = _dedupe([*ancestor_homes, *tree_homes, *home_homes])
    conflicts = sorted(
        {item["path"]: item for item in [*ancestor_conflicts, *tree_conflicts, *home_conflicts]}.values(),
        key=lambda item: item["path"],
    )
    return homes, conflicts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find current-model brains, or bootstrap candidates with --candidates."
    )
    parser.add_argument(
        "--candidates",
        action="store_true",
        help="Use broad notes-folder heuristics for bootstrap destination suggestions.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="With PATH: ignore the default and list every brain reachable from PATH and HOME.",
    )
    parser.add_argument(
        "--no-scan",
        action="store_true",
        help="With PATH: never scan HOME (ancestor and default only). Fast; used by hooks.",
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
        base = {
            "search_root": str(target),
            "provided_path": True,
            "mode": "candidates" if args.candidates else "implanted",
            "expected_model_root": str(current_model_root()),
        }
        if args.candidates:
            homes = [candidate_info(target)]
            print(json.dumps({**base, "homes": homes, "conflicts": [], "count": len(homes)}))
            return 0
        if args.all:
            homes, conflicts = search_all(target)
            print(json.dumps({
                **base, "status": "candidates" if homes else "none", "source": "all",
                "homes": homes, "candidates": [], "conflicts": conflicts, "count": len(homes),
            }))
            return 0 if homes else 1
        fields, resolved = resolve_from_path(target, scan_home=not args.no_scan)
        fields.setdefault("candidates", [])
        print(json.dumps({**base, **fields, "count": len(fields["homes"])}))
        return 0 if resolved else 1

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

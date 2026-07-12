#!/usr/bin/env python3
"""Find Obsidian vaults by searching for .obsidian directories.

Usage:
    python3 find_vaults.py                     # search from home directory
    python3 find_vaults.py /path/to/search     # search from given path
    python3 find_vaults.py /path/to/vault      # check if path is a vault

Exit codes:
    0 - vault(s) found
    1 - no vaults found or path does not exist

Output: JSON with keys:
    - search_root: where the search started
    - provided_path: whether a path was explicitly provided (bool)
    - is_direct_vault: whether the provided path itself is a vault (bool)
    - vaults: list of vault objects (see below)
    - count: number of vaults found

Vault object keys:
    - path: absolute path to the vault root
    - name: directory name of the vault
    - has_agents_md: whether AGENTS.md exists at vault root (bool)
    - has_brain_md: whether BRAIN.md exists at vault root (bool)
    - is_nested: whether this vault lives inside another found vault (bool)
    - parent_vault: path of the parent vault if is_nested, else null
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


def vault_info(path: Path) -> dict:
    return {
        "path": str(path),
        "name": path.name,
        "has_agents_md": (path / "AGENTS.md").is_file(),
        "has_brain_md": (path / "BRAIN.md").is_file(),
        "is_nested": False,
        "parent_vault": None,
    }


def find_vaults_under(root: Path, max_depth: int = 4) -> list[dict]:
    result = []
    visited = set()

    def _walk(current: Path, depth: int):
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            return

        if (current / ".obsidian").is_dir():
            result.append(vault_info(current))

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

    parent_paths = {v["path"] for v in result}
    for v in result:
        ancestors = [c for c in parent_paths if c != v["path"] and v["path"].startswith(c + "/")]
        if ancestors:
            v["is_nested"] = True
            v["parent_vault"] = max(ancestors, key=len)  # closest ancestor = longest prefix

    return sorted(result, key=lambda v: v["path"])


def main() -> int:
    provided_path = len(sys.argv) > 1

    if provided_path:
        raw = sys.argv[1].strip()
        target = Path(raw).expanduser().resolve()

        if not target.exists():
            print(json.dumps({
                "search_root": str(target),
                "provided_path": True,
                "is_direct_vault": False,
                "vaults": [],
                "count": 0,
                "error": f"Path does not exist: {target}",
            }))
            return 1

        if is_vault(target):
            info = vault_info(target)
            print(json.dumps({
                "search_root": str(target),
                "provided_path": True,
                "is_direct_vault": True,
                "vaults": [info],
                "count": 1,
            }))
            return 0

        vaults = find_vaults_under(target)
        print(json.dumps({
            "search_root": str(target),
            "provided_path": True,
            "is_direct_vault": False,
            "vaults": vaults,
            "count": len(vaults),
        }))
        return 0 if vaults else 1

    home = Path.home()
    vaults = find_vaults_under(home)
    print(json.dumps({
        "search_root": str(home),
        "provided_path": False,
        "is_direct_vault": False,
        "vaults": vaults,
        "count": len(vaults),
    }))
    return 0 if vaults else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Remove .DS_Store noise files from visible vault content.

Dry-run by default. Pass --apply to actually delete the files. Top-level
dotfile dirs (`.git`, `.obsidian`, `.WIP_<timestamp>`, ...) are skipped —
they may contain their own `.DS_Store` files that we should not touch.

Intended to run as a maintenance step and as a pre-check inside
`vault_setup.py` before `cleanup_empty_dirs_recursively`, so directories
that hold only `.DS_Store` are correctly detected as empty afterwards.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Filenames to remove. Extend this list in place when a new universal noise
# pattern emerges (e.g. `Thumbs.db` on Windows, `@eaDir` on Synology). If the
# list grows beyond ~3 entries or needs per-vault customization, rename the
# script to `cleanup_noise_files.py` and expose `--pattern` on the CLI.
NOISE_FILE_NAMES = [".DS_Store"]


def find_noise_files(vault: Path) -> list[Path]:
    """Return all noise files inside visible vault subtrees, sorted by path.

    Skips top-level dotfile dirs entirely (they may have their own noise we
    should not touch). Skips symlinks. Walks all visible top-level dirs
    recursively.
    """
    found: list[Path] = []
    try:
        top_entries = list(vault.iterdir())
    except OSError:
        return found
    for top in top_entries:
        try:
            if top.is_symlink():
                continue
            if top.is_dir():
                if top.name.startswith("."):
                    continue  # do not descend into dotfile dirs (.git, .obsidian, ...)
                for path in top.rglob("*"):
                    try:
                        if (
                            path.is_file()
                            and not path.is_symlink()
                            and path.name in NOISE_FILE_NAMES
                        ):
                            found.append(path)
                    except OSError:
                        continue
            elif top.is_file():
                # Files at the vault root: match by name regardless of leading dot.
                # NOISE_FILE_NAMES contains dotfile patterns (e.g. ".DS_Store") that
                # must be removed even when sitting loose at the root.
                if top.name in NOISE_FILE_NAMES:
                    found.append(top)
        except OSError:
            continue
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove .DS_Store noise files from visible vault content."
    )
    parser.add_argument("--vault-root", required=True, help="Path to the vault root.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply removals. Default is dry-run.",
    )
    args = parser.parse_args()

    vault = Path(args.vault_root).expanduser().resolve()
    if not vault.is_dir():
        print(f"ERROR: vault root not found: {vault}", file=sys.stderr)
        return 1

    print("# Cleanup of noise files")
    print(f"mode: {'apply' if args.apply else 'dry-run'}")
    print(f"vault: {vault}")
    print(f"patterns: {', '.join(NOISE_FILE_NAMES)}")

    found = find_noise_files(vault)
    if not found:
        print("  no noise files found")
        return 0

    failures = 0
    for path in found:
        rel = path.relative_to(vault)
        print(f"  removing: {rel}")
        if args.apply:
            try:
                path.unlink()
            except OSError as exc:
                print(f"    WARNING: unlink failed: {exc}", file=sys.stderr)
                failures += 1

    if not args.apply:
        print(f"  (dry-run: no files removed, {len(found)} would be removed)")
    else:
        removed = len(found) - failures
        print(f"  removed {removed} file(s)" + (f" ({failures} failures)" if failures else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

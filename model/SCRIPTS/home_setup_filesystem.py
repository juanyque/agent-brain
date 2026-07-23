from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _common import Reporter
from brain_state import OPERATIONAL_TOP_LEVEL_DIRS, STAGING_DIR_NAME, staging_status


def cleanup_ds_store_command(
    common: Path,
    brain_root: Path,
    applied: bool,
) -> list[str]:
    repo_root = common.parent
    command = [
        sys.executable,
        str(repo_root / "skills" / "brain" / "scripts" / "cleanup_ds_store.py"),
        "--brain-root",
        str(brain_root),
    ]
    if applied:
        command.append("--apply")
    return command


def run_cleanup_ds_store(
    common: Path,
    brain_root: Path,
    applied: bool,
    reporter: Reporter,
) -> None:
    command = cleanup_ds_store_command(common, brain_root, applied)
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.stdout:
        for line in result.stdout.rstrip().splitlines():
            reporter.write(line)
    if result.stderr:
        for line in result.stderr.rstrip().splitlines():
            reporter.write(f"STDERR: {line}")
    if result.returncode != 0:
        reporter.write(f"  WARNING: cleanup_ds_store exited with code {result.returncode}")
    reporter.write("")


def cleanup_empty_dirs_recursively(
    brain_root: Path,
    reporter: Reporter,
    dry_run: bool,
) -> None:
    candidates: list[Path] = []
    try:
        top_entries = list(brain_root.iterdir())
    except OSError:
        return
    for top in top_entries:
        try:
            if top.is_symlink() or not top.is_dir() or top.name.startswith("."):
                continue
        except OSError:
            continue
        candidates.append(top)
        for path in top.rglob("*"):
            try:
                if not path.is_symlink() and path.is_dir():
                    candidates.append(path)
            except OSError:
                continue
    candidates.sort(key=lambda path: len(path.parts), reverse=True)
    removed: list[Path] = []
    removed_set: set[Path] = set()
    for path in candidates:
        try:
            children = list(path.iterdir())
        except OSError:
            continue
        if any(child not in removed_set for child in children):
            continue
        if not dry_run:
            try:
                path.rmdir()
            except OSError:
                continue
        removed.append(path.relative_to(brain_root))
        removed_set.add(path)
    if not removed:
        return
    reporter.write("# Cleanup of empty directories")
    for rel in removed:
        reporter.write(f"  removing empty: {rel}/")
    if dry_run:
        reporter.write("  (dry-run: no dirs removed)")
    reporter.write("")


def collect_movable_items(brain_root: Path) -> list[Path]:
    return sorted(
        path
        for path in brain_root.iterdir()
        if not path.name.startswith(".")
        and path.name not in OPERATIONAL_TOP_LEVEL_DIRS
    )


def git_mv_to_staging(
    brain_root: Path,
    reporter: Reporter,
    dry_run: bool,
) -> None:
    staging = brain_root / STAGING_DIR_NAME
    status, _count = staging_status(brain_root)

    if status == "has-content":
        reporter.write(f"  {STAGING_DIR_NAME}: already exists with content, skipping")
        return

    items = collect_movable_items(brain_root)
    if not items:
        reporter.write(f"  {STAGING_DIR_NAME}: brain root is empty, nothing to move")
        return

    if status == "missing":
        if dry_run:
            reporter.write(f"  will create: {STAGING_DIR_NAME}/")
        else:
            staging.mkdir()

    reporter.write(f"  items to move into {STAGING_DIR_NAME}/:")
    for item in items:
        reporter.write(f"    {item.name}")
        if not dry_run:
            if item.is_dir() and not any(item.iterdir()):
                dest = staging / item.name
                dest.mkdir()
                item.rmdir()
                reporter.write("      (empty dir, moved directly)")
            else:
                result = subprocess.run(
                    ["git", "mv", item.name, f"{STAGING_DIR_NAME}/{item.name}"],
                    cwd=brain_root,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if result.returncode != 0:
                    reporter.write(
                        f"    WARNING: git mv failed: {result.stderr.strip()}"
                    )
    if dry_run:
        reporter.write("  (dry-run: no files moved)")

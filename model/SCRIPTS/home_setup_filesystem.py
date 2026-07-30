from __future__ import annotations

import errno
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final, Literal, assert_never

from _common import Reporter
from brain_state import OPERATIONAL_TOP_LEVEL_DIRS, STAGING_DIR_NAME, staging_status
from home_setup_content import SCAFFOLD_DIRECTORIES, TEMPLATE_SYMLINKS

SymlinkPolicy = Literal["copy", "keep"]
SymlinkTargetStatus = Literal["available", "missing", "cycle"]
CANONICAL_TOP_LEVEL_DIRS: Final = frozenset(
    Path(directory).parts[0]
    for directory in (*SCAFFOLD_DIRECTORIES, *TEMPLATE_SYMLINKS, "TASK_TYPES")
)


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


def symlink_target_status(path: Path) -> SymlinkTargetStatus:
    try:
        path.resolve(strict=True)
    except FileNotFoundError:
        return "missing"
    except RuntimeError:
        return "cycle"
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return "cycle"
        raise
    return "available"


def move_to_staging(
    brain_root: Path,
    reporter: Reporter,
    dry_run: bool,
    symlink_policy: SymlinkPolicy | None = None,
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

    symlinks = [item for item in items if item.is_symlink()]
    target_statuses = {item: symlink_target_status(item) for item in symlinks}
    missing_targets = [
        item for item, status in target_statuses.items() if status == "missing"
    ]
    cyclic_targets = [
        item for item, status in target_statuses.items() if status == "cycle"
    ]
    if symlinks:
        reporter.write("  top-level symlinks:")
        for item in symlinks:
            match target_statuses[item]:
                case "available":
                    copy_status = "allowed"
                    resolved = item.resolve(strict=False)
                case "missing":
                    copy_status = "blocked-missing-target"
                    resolved = item.resolve(strict=False)
                case "cycle":
                    copy_status = "blocked-cycle"
                    resolved = "cycle"
                case unreachable:
                    assert_never(unreachable)
            keep_status = (
                "blocked-canonical"
                if item.name in CANONICAL_TOP_LEVEL_DIRS
                else "allowed"
            )
            reporter.write(
                f"    symlink: {item.name} -> {item.readlink()} "
                f"(resolves: {resolved}; copy: {copy_status}; "
                f"keep: {keep_status})"
            )
        reporter.write(
            "  symlink_policy: "
            + (symlink_policy if symlink_policy is not None else "required")
        )
        if cyclic_targets:
            recommendation = "repair-cycle-then-copy"
        elif missing_targets:
            recommendation = "repair-target-then-copy"
        else:
            recommendation = "copy"
        reporter.write(f"  recommended_symlink_policy: {recommendation}")

    if symlinks and not dry_run and symlink_policy is None:
        names = ", ".join(item.name for item in symlinks)
        raise SystemExit(
            f"Symlink policy required for: {names}. "
            "Re-run with --symlink-policy copy (recommended) or keep."
        )

    if cyclic_targets and not dry_run and symlink_policy == "copy":
        names = ", ".join(item.name for item in cyclic_targets)
        raise SystemExit(
            f"Cannot copy cyclic symlinks: {names}. "
            "Repair or replace the links, or use --symlink-policy keep for "
            "non-canonical links."
        )

    if missing_targets and not dry_run and symlink_policy == "copy":
        names = ", ".join(item.name for item in missing_targets)
        raise SystemExit(
            f"Cannot copy symlinks with missing targets: {names}. "
            "Repair the targets, or use --symlink-policy keep for non-canonical links."
        )

    match symlink_policy:
        case "keep":
            blocked = [item for item in symlinks if item.name in CANONICAL_TOP_LEVEL_DIRS]
            if blocked:
                names = ", ".join(item.name for item in blocked)
                raise SystemExit(
                    "Cannot keep symlinks that occupy canonical model directories: "
                    f"{names}. Re-run with --symlink-policy copy."
                )
            items_to_move = [item for item in items if not item.is_symlink()]
            reporter.write("  external symlinks kept at brain root:")
            for item in symlinks:
                reporter.write(f"    {item.name}")
        case "copy" | None:
            items_to_move = items
        case unreachable:
            assert_never(unreachable)

    if not items_to_move:
        reporter.write(f"  {STAGING_DIR_NAME}: no content selected to move")
        return

    if status == "missing":
        if dry_run:
            reporter.write(f"  will create: {STAGING_DIR_NAME}/")
        else:
            staging.mkdir()

    reporter.write(f"  items to move into {STAGING_DIR_NAME}/:")
    for item in items_to_move:
        reporter.write(f"    {item.name}")
        if not dry_run:
            destination = staging / item.name
            try:
                if item.is_symlink():
                    if item.is_dir():
                        shutil.copytree(item, destination)
                    else:
                        shutil.copy2(item, destination, follow_symlinks=True)
                    item.unlink()
                else:
                    item.rename(destination)
            except OSError as exc:
                reporter.write(f"    WARNING: filesystem move failed: {exc}")
    if dry_run:
        reporter.write("  (dry-run: no files moved)")

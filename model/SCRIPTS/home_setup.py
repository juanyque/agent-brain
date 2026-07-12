#!/usr/bin/env python3
"""Attach a brain to the agent-brain model — structure only (D21).

Handles: pre-cleanup (.DS_Store, empty dirs), staging (virgin -> _STAGING/),
and model attachment (_COMMON symlink, wrappers, templates). No runtime logic;
runtime_manager.py handles all runtime concerns.

Dry-run by default. Pass --apply to execute.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from brain_state import (  # noqa: E402  (lives next to this script)
    COMMON_LINK_NAME,
    OPERATIONAL_TOP_LEVEL_DIRS,
    STAGING_DIR_NAME,
    link_status,
    staging_status,
)
from _common import Reporter, build_command_string  # noqa: E402  (lives next to this script)

WRAPPERS = {
    "AGENTS.md": "AGENTS.common.md",
    "VAULT.md": "VAULT.common.md",
    "JOBS.md": "JOBS.common.md",
    "RULES-FILE-NAMING.md": "RULES-FILE-NAMING.common.md",
    "RULES-LINKS.md": "RULES-LINKS.common.md",
    "RULES-DAILY-NOTES.md": "RULES-DAILY-NOTES.common.md",
    "RULES-SESSION-LIFECYCLE.md": "RULES-SESSION-LIFECYCLE.common.md",
}

TEMPLATE_SYMLINKS = {
    "TEMPLATES/WIP Template.md": "TEMPLATES/TEMPLATE.wip.common.md",
    "TEMPLATES/WIP Session Template.md": "TEMPLATES/TEMPLATE.wip-session.common.md",
    "TEMPLATES/Daily Note Template.md": "TEMPLATES/TEMPLATE.daily-note.common.md",
    "TEMPLATES/Issue Template.md": "TEMPLATES/TEMPLATE.issue.common.md",
}


def resolve_common_root(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def wrapper_text(local_name: str, common_name: str) -> str:
    title = Path(local_name).stem
    return (
        f"# {title}\n\n"
        f"This vault follows the shared model in `_COMMON/{common_name}`.\n"
    )


def discover_task_type_wrappers(common: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    task_dir = common / "TASK_TYPES"
    if not task_dir.is_dir():
        return result
    for source in sorted(task_dir.glob("*.common.md")):
        common_rel = f"TASK_TYPES/{source.name}"
        local_basename = source.stem
        if local_basename.endswith(".common"):
            local_basename = local_basename[: -len(".common")]
        local_rel = f"TASK_TYPES/{local_basename}.md"
        result[local_rel] = common_rel
    return result


def cleanup_ds_store_command(common: Path, vault: Path, applied: bool) -> list[str]:
    repo_root = common.parent
    command = [
        sys.executable,
        str(repo_root / "skills" / "brain" / "scripts" / "cleanup_ds_store.py"),
        "--vault-root",
        str(vault),
    ]
    if applied:
        command.append("--apply")
    return command


def run_cleanup_ds_store(
    common: Path, vault: Path, applied: bool, reporter: Reporter
) -> None:
    command = cleanup_ds_store_command(common, vault, applied)
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
    vault: Path,
    reporter: Reporter,
    dry_run: bool,
) -> None:
    candidates: list[Path] = []
    try:
        top_entries = list(vault.iterdir())
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
    candidates.sort(key=lambda p: len(p.parts), reverse=True)
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
        removed.append(path.relative_to(vault))
        removed_set.add(path)
    if not removed:
        return
    reporter.write("# Cleanup of empty directories")
    for rel in removed:
        reporter.write(f"  removing empty: {rel}/")
    if dry_run:
        reporter.write("  (dry-run: no dirs removed)")
    reporter.write("")


def collect_movable_items(vault: Path) -> list[Path]:
    return sorted(
        p for p in vault.iterdir()
        if not p.name.startswith(".") and p.name not in OPERATIONAL_TOP_LEVEL_DIRS
    )


def git_mv_to_staging(
    vault: Path,
    reporter: Reporter,
    dry_run: bool,
) -> None:
    staging = vault / STAGING_DIR_NAME
    status, _count = staging_status(vault)

    if status == "has-content":
        reporter.write(f"  {STAGING_DIR_NAME}: already exists with content, skipping")
        return

    items = collect_movable_items(vault)
    if not items:
        reporter.write(f"  {STAGING_DIR_NAME}: vault root is empty, nothing to move")
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
                reporter.write(f"      (empty dir, moved directly)")
            else:
                result = subprocess.run(
                    ["git", "mv", item.name, f"{STAGING_DIR_NAME}/{item.name}"],
                    cwd=vault,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if result.returncode != 0:
                    reporter.write(f"    WARNING: git mv failed: {result.stderr.strip()}")
    if dry_run:
        reporter.write(f"  (dry-run: no files moved)")


def via_common_symlink_target(common_rel: str, link_path: Path, vault: Path) -> str:
    rel = link_path.relative_to(vault)
    depth = len(rel.parts) - 1
    prefix = ("../" * depth) if depth > 0 else ""
    return f"{prefix}{COMMON_LINK_NAME}/{common_rel}"


def print_plan(
    vault: Path,
    common: Path,
    reporter: Reporter,
    applied: bool,
    command_string: str,
    skip_full_reorder: bool,
) -> None:
    link_st, desired = link_status(vault, common)
    reporter.write("# Brain setup (structure)")
    reporter.write("")
    reporter.write(f"mode: {'apply' if applied else 'dry-run'}")
    reporter.write(f"command: {command_string}")
    reporter.write(f"vault: {vault}")
    reporter.write(f"common: {common}")
    reporter.write(f"{COMMON_LINK_NAME}: {link_st} -> {desired}")

    if link_st != "ok" and not skip_full_reorder:
        stg_status, stg_count = staging_status(vault)
        reporter.write(f"{STAGING_DIR_NAME}: {stg_status}" + (f" ({stg_count} items)" if stg_count else ""))
        if stg_status != "has-content":
            items = collect_movable_items(vault)
            reporter.write(f"  {len(items)} non-hidden items will be moved to {STAGING_DIR_NAME}/")
    elif link_st != "ok" and skip_full_reorder:
        reporter.write(f"{STAGING_DIR_NAME}: skipped by --skip-full-reorder")
    elif link_st == "ok":
        reporter.write(f"{COMMON_LINK_NAME}: already attached")

    reporter.write("wrappers:")
    task_type_wrappers = discover_task_type_wrappers(common)
    combined_wrappers = list(WRAPPERS.items()) + list(task_type_wrappers.items())
    for local_name, common_name in combined_wrappers:
        local_path = vault / local_name
        common_path = common / common_name
        if local_path.exists():
            local_status = "exists, will not overwrite"
        elif common_path.exists():
            local_status = "missing, can create"
        else:
            local_status = f"missing common source: {common_name}"
        reporter.write(f"  {local_name}: {local_status}")
    reporter.write("template symlinks:")
    for local_rel, common_rel in TEMPLATE_SYMLINKS.items():
        local_path = vault / local_rel
        common_path = common / common_rel
        if local_path.is_symlink():
            tmpl_status = "exists (symlink)"
        elif local_path.exists():
            tmpl_status = "exists (file), will not overwrite"
        elif not common_path.exists():
            tmpl_status = f"missing common source: {common_rel}"
        else:
            tmpl_status = "can create symlink"
        reporter.write(f"  {local_rel}: {tmpl_status}")
    reporter.write("next steps:")
    reporter.write("  Runtime wiring is handled by runtime_manager.py.")
    reporter.write("  Start guided standardization with the brain skill.")


def apply(
    vault: Path,
    common: Path,
    skip_full_reorder: bool,
    reporter: Reporter,
) -> None:
    status, desired = link_status(vault, common)

    if status == "missing" and not skip_full_reorder:
        git_mv_to_staging(vault, reporter, dry_run=False)

    link_path = vault / COMMON_LINK_NAME

    if status == "missing":
        link_path.symlink_to(desired, target_is_directory=True)
    elif status != "ok":
        raise SystemExit(f"Refusing to modify {link_path}: {status}")

    task_type_wrappers = discover_task_type_wrappers(common)
    combined_wrappers = list(WRAPPERS.items()) + list(task_type_wrappers.items())
    for local_name, common_name in combined_wrappers:
        local_path = vault / local_name
        common_path = common / common_name
        if local_path.exists():
            continue
        if not common_path.exists():
            continue
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(wrapper_text(local_name, common_name), encoding="utf-8")

    for local_rel, common_rel in TEMPLATE_SYMLINKS.items():
        local_path = vault / local_rel
        common_path = common / common_rel
        if local_path.exists() or local_path.is_symlink():
            continue
        if not common_path.exists():
            continue
        local_path.parent.mkdir(parents=True, exist_ok=True)
        target = via_common_symlink_target(common_rel, local_path, vault)
        local_path.symlink_to(target)


def validate(vault: Path, common: Path) -> list[str]:
    errors = []
    status, _desired = link_status(vault, common)
    if status != "ok":
        errors.append(f"{COMMON_LINK_NAME} status is {status}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Attach a brain to the agent-brain model (structure only)")
    parser.add_argument("--vault", required=True, help="Path to the brain root")
    parser.add_argument("--common", help="Path to the model root. Defaults to this script's repo model/.")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Default is dry-run.")
    parser.add_argument("--skip-full-reorder", action="store_true", help="Skip staging sweep. Only attach _COMMON + wrappers.")
    args = parser.parse_args()
    reporter = Reporter(Path(__file__).with_suffix(".log"))
    command_string = build_command_string()

    try:
        vault = Path(args.vault).expanduser().resolve()
        common = resolve_common_root(args.common)

        if not vault.is_dir():
            raise SystemExit(f"Brain directory not found: {vault}")
        if not common.is_dir():
            raise SystemExit(f"Model directory not found: {common}")

        if not args.skip_full_reorder:
            run_cleanup_ds_store(common, vault, applied=args.apply, reporter=reporter)
            cleanup_empty_dirs_recursively(vault, reporter, dry_run=not args.apply)

        print_plan(
            vault,
            common,
            reporter=reporter,
            applied=args.apply,
            command_string=command_string,
            skip_full_reorder=args.skip_full_reorder,
        )
        if not args.apply:
            link_st, _ = link_status(vault, common)
            if link_st != "ok" and not args.skip_full_reorder:
                reporter.write("")
                git_mv_to_staging(vault, reporter, dry_run=True)
            reporter.write("Dry run only. Re-run with --apply to create missing safe items.")
            reporter.flush()
            return 0

        apply(
            vault,
            common,
            skip_full_reorder=args.skip_full_reorder,
            reporter=reporter,
        )
        errors = validate(vault, common)
        if errors:
            for error in errors:
                reporter.write(f"ERROR: {error}")
            reporter.flush()
            return 1
        reporter.write("Brain structure setup completed successfully.")
        reporter.flush()
        return 0
    except SystemExit as exc:
        reporter.write(f"ERROR: {exc}")
        reporter.flush()
        raise


if __name__ == "__main__":
    raise SystemExit(main())

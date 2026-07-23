#!/usr/bin/env python3
"""Attach a brain to the agent-brain model — structure only (D21).

Handles: pre-cleanup (.DS_Store, empty dirs), staging (virgin -> _STAGING/),
and model attachment (_COMMON symlink, wrappers, templates). No runtime logic;
runtime_manager.py handles all runtime concerns.

Dry-run by default. Pass --apply to execute.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from brain_state import (  # noqa: E402  (lives next to this script)
    COMMON_LINK_NAME,
    STAGING_DIR_NAME,
    link_status,
    staging_status,
)
from _common import Reporter, build_command_string  # noqa: E402  (lives next to this script)
from home_setup_content import (  # noqa: E402  (lives next to this script)
    TEMPLATE_SYMLINKS,
    WRAPPERS,
    apply_managed_content,
    discover_task_type_wrappers,
    is_current_template_symlink,
    managed_content_errors,
    via_common_symlink_target,
)
from home_setup_filesystem import (  # noqa: E402  (lives next to this script)
    cleanup_empty_dirs_recursively,
    collect_movable_items,
    git_mv_to_staging,
    run_cleanup_ds_store,
)


def resolve_common_root(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def describe_common_entry(link_path: Path) -> str:
    """Describe the current _COMMON entry without losing broken-link context."""
    if link_path.is_symlink():
        raw_target = link_path.readlink()
        resolved_target = link_path.resolve(strict=False)
        missing = "; target missing" if not resolved_target.exists() else ""
        return f"symlink -> {raw_target} (resolves to {resolved_target}{missing})"
    if link_path.is_dir():
        return f"directory at {link_path.resolve(strict=False)}"
    if link_path.is_file():
        return f"regular file at {link_path.resolve(strict=False)}"
    if link_path.exists():
        return f"non-symlink entry at {link_path.resolve(strict=False)}"
    return "missing"


def describe_desired_common(common: Path, desired: str) -> str:
    return f"symlink -> {desired} (resolves to {common.resolve(strict=False)})"


def report_common_status(
    brain_root: Path,
    common: Path,
    status: str,
    desired: str,
    reporter: Reporter,
) -> None:
    if status.startswith("conflict"):
        reporter.write(f"{COMMON_LINK_NAME}:")
        reporter.write(f"  status: {status}")
        reporter.write(
            f"  current: {describe_common_entry(brain_root / COMMON_LINK_NAME)}"
        )
        reporter.write(f"  desired: {describe_desired_common(common, desired)}")
        return
    reporter.write(f"{COMMON_LINK_NAME}: {status} -> {desired}")


def print_plan(
    brain_root: Path,
    common: Path,
    reporter: Reporter,
    applied: bool,
    command_string: str,
    skip_full_reorder: bool,
) -> None:
    link_st, desired = link_status(brain_root, common)
    reporter.write("# Brain setup (structure)")
    reporter.write("")
    reporter.write(f"mode: {'apply' if applied else 'dry-run'}")
    reporter.write(f"command: {command_string}")
    reporter.write(f"brain: {brain_root}")
    reporter.write(f"common: {common}")
    report_common_status(brain_root, common, link_st, desired, reporter)

    if link_st == "missing" and not skip_full_reorder:
        stg_status, stg_count = staging_status(brain_root)
        reporter.write(f"{STAGING_DIR_NAME}: {stg_status}" + (f" ({stg_count} items)" if stg_count else ""))
        if stg_status != "has-content":
            items = collect_movable_items(brain_root)
            reporter.write(f"  {len(items)} non-hidden items will be moved to {STAGING_DIR_NAME}/")
    elif link_st == "missing" and skip_full_reorder:
        reporter.write(f"{STAGING_DIR_NAME}: skipped by --skip-full-reorder")
    elif link_st.startswith("conflict"):
        reporter.write(f"{STAGING_DIR_NAME}: unchanged while resolving {COMMON_LINK_NAME} conflict")
    elif link_st == "ok":
        reporter.write(f"{COMMON_LINK_NAME}: already attached")

    reporter.write("wrappers:")
    task_type_wrappers = discover_task_type_wrappers(common)
    combined_wrappers = list(WRAPPERS.items()) + list(task_type_wrappers.items())
    for local_name, common_name in combined_wrappers:
        local_path = brain_root / local_name
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
        local_path = brain_root / local_rel
        common_path = common / common_rel
        desired_target = via_common_symlink_target(
            common_rel,
            local_path,
            brain_root,
        )
        if not common_path.exists():
            tmpl_status = f"missing common source: {common_rel}"
        elif is_current_template_symlink(local_path, common_path):
            tmpl_status = "current"
        elif local_path.is_symlink():
            tmpl_status = (
                f"wrong target: {local_path.readlink()}; "
                f"will relink to {desired_target}"
            )
        elif local_path.exists():
            tmpl_status = "exists (file), will not overwrite"
        else:
            tmpl_status = f"can create symlink -> {desired_target}"
        reporter.write(f"  {local_rel}: {tmpl_status}")
    reporter.write("next steps:")
    reporter.write("  Runtime wiring is handled by runtime_manager.py.")
    reporter.write("  Start guided standardization with the brain skill.")


def apply(
    brain_root: Path,
    common: Path,
    skip_full_reorder: bool,
    switch_model: bool,
    reporter: Reporter,
) -> None:
    from datetime import datetime, timezone

    status, desired = link_status(brain_root, common)

    if status == "missing" and not skip_full_reorder:
        git_mv_to_staging(brain_root, reporter, dry_run=False)

    link_path = brain_root / COMMON_LINK_NAME

    if status == "missing":
        link_path.symlink_to(desired, target_is_directory=True)
    elif status == "ok":
        pass
    elif status.startswith("conflict") and switch_model:
        previous = describe_common_entry(link_path)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = link_path.with_name(f"{COMMON_LINK_NAME}.backup-{ts}")
        if link_path.is_symlink() or link_path.exists():
            link_path.rename(backup)
        link_path.symlink_to(desired, target_is_directory=True)
        reporter.write(f"  SWITCHED {COMMON_LINK_NAME}")
        reporter.write(f"    previous: {previous}")
        reporter.write(f"    desired: {describe_desired_common(common, desired)}")
        reporter.write(f"    backup: {backup}")
    elif status.startswith("conflict"):
        raise SystemExit(
            f"{COMMON_LINK_NAME} conflict\n"
            f"  status: {status}\n"
            f"  current: {describe_common_entry(link_path)}\n"
            f"  desired: {describe_desired_common(common, desired)}\n"
            "  action: pass --switch-model to preserve the current entry as "
            f"{COMMON_LINK_NAME}.backup-<ts> and install the desired symlink."
        )
    else:
        raise SystemExit(f"Unexpected _COMMON status: {status}")

    apply_managed_content(brain_root, common, reporter)


def validate(brain_root: Path, common: Path) -> list[str]:
    errors: list[str] = []
    status, _desired = link_status(brain_root, common)
    if status != "ok":
        errors.append(f"{COMMON_LINK_NAME} status is {status}")
    errors.extend(managed_content_errors(brain_root, common))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Attach a brain to the agent-brain model (structure only)")
    parser.add_argument("--brain", required=True, help="Path to the brain root")
    parser.add_argument("--common", help="Path to the model root. Defaults to this script's repo model/.")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Default is dry-run.")
    parser.add_argument("--skip-full-reorder", action="store_true", help="Skip staging sweep. Only attach _COMMON + wrappers.")
    parser.add_argument("--switch-model", action="store_true", help="Repoint _COMMON if it conflicts (D25). A .backup-<ts> is created.")
    args = parser.parse_args()
    reporter = Reporter(Path(__file__).with_suffix(".log"))
    command_string = build_command_string()

    try:
        brain_root = Path(args.brain).expanduser().resolve()
        common = resolve_common_root(args.common)

        if not brain_root.is_dir():
            raise SystemExit(f"Brain directory not found: {brain_root}")
        if not common.is_dir():
            raise SystemExit(f"Model directory not found: {common}")

        if not args.skip_full_reorder:
            run_cleanup_ds_store(common, brain_root, applied=args.apply, reporter=reporter)
            cleanup_empty_dirs_recursively(brain_root, reporter, dry_run=not args.apply)

        print_plan(
            brain_root,
            common,
            reporter=reporter,
            applied=args.apply,
            command_string=command_string,
            skip_full_reorder=args.skip_full_reorder,
        )
        if not args.apply:
            link_st, _ = link_status(brain_root, common)
            if link_st.startswith("conflict"):
                reporter.write("")
                reporter.write(f"  CONFLICT: {COMMON_LINK_NAME} will remain unchanged")
                if args.switch_model:
                    reporter.write(
                        f"  apply action: backup current {COMMON_LINK_NAME} entry, then install desired symlink"
                    )
                else:
                    reporter.write(
                        "  action required: review current vs desired, then pass "
                        "--switch-model to preserve and replace the current entry"
                    )
            elif link_st != "ok" and not args.skip_full_reorder:
                reporter.write("")
                git_mv_to_staging(brain_root, reporter, dry_run=True)
            reporter.write("Dry run only. Re-run with --apply to create missing safe items.")
            reporter.flush()
            return 0

        apply(
            brain_root,
            common,
            skip_full_reorder=args.skip_full_reorder,
            switch_model=args.switch_model,
            reporter=reporter,
        )
        errors = validate(brain_root, common)
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

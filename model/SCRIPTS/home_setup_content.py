from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from _common import Reporter
from brain_state import COMMON_LINK_NAME

WRAPPERS = {
    "AGENTS.md": "AGENTS.common.md",
    "BRAIN.md": "BRAIN.common.md",
    "JOBS.md": "JOBS.common.md",
}

TEMPLATE_SYMLINKS = {
    "TEMPLATES/WIP Template.md": "TEMPLATES/TEMPLATE.wip.common.md",
    "TEMPLATES/WIP Session Template.md": "TEMPLATES/TEMPLATE.wip-session.common.md",
    "TEMPLATES/Daily Note Template.md": "TEMPLATES/TEMPLATE.daily-note.common.md",
    "TEMPLATES/Issue Template.md": "TEMPLATES/TEMPLATE.issue.common.md",
}

LOCAL_STATE_FILES: Final = {
    "JOBS_LOGS.md": (
        "# JOBS_LOGS\n\n"
        "## Daily (Day change)\n\n"
        "## Session consolidation\n\n"
        "## Weekly\n\n"
        "## Monthly\n\n"
        "## Yearly\n"
    ),
}

SCAFFOLD_DIRECTORIES = (
    "INBOX",
    "WIP",
    "WIP/SESSIONS",
    "JOURNAL",
    "MEMORY",
    "BACKLOG",
    "ARCHIVED",
    "REPORTS",
    "OUTBOX",
    "QUARANTINE",
    "QUARANTINE/TRASH",
    "QUARANTINE/ATTACHMENTS",
)


def report_content_directories(brain_root: Path, reporter: Reporter) -> None:
    reporter.write("scaffold directories:")
    for directory in SCAFFOLD_DIRECTORIES:
        status = "current" if (brain_root / directory).is_dir() else "missing, can create"
        reporter.write(f"  {directory}/: {status}")
    reporter.write("local state:")
    for local_name in LOCAL_STATE_FILES:
        status = "exists, will not overwrite" if entry_exists_no_follow(brain_root / local_name) else "missing, can create"
        reporter.write(f"  {local_name}: {status}")


def wrapper_text(local_name: str, common_name: str) -> str:
    title = Path(local_name).stem
    wrapper_kind = wrapper_kind_for(local_name)
    return (
        f"# {title}\n\n"
        f"This local {wrapper_kind} wrapper follows `_COMMON/{common_name}`.\n\n"
        "Read the common target first, then apply any local additions, "
        "overrides, replacements, or new sections here.\n"
    )


def wrapper_kind_for(local_name: str) -> str:
    path = Path(local_name)
    if path.parts and path.parts[0] == "TASK_TYPES":
        return "task-type"
    if path.name.startswith("RULES-"):
        return "rule"
    return "model"


def discover_rule_wrappers(common: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for source in sorted(common.glob("RULES-*.common.md")):
        local_name = source.name.removesuffix(".common.md") + ".md"
        result[local_name] = source.name
    return result


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


def discover_wrappers(common: Path) -> dict[str, str]:
    return {
        **WRAPPERS,
        **discover_rule_wrappers(common),
        **discover_task_type_wrappers(common),
    }


def via_common_symlink_target(
    common_rel: str,
    link_path: Path,
    brain_root: Path,
) -> str:
    rel = link_path.relative_to(brain_root)
    depth = len(rel.parts) - 1
    prefix = "../" * depth
    return f"{prefix}{COMMON_LINK_NAME}/{common_rel}"


def is_current_template_symlink(local_path: Path, common_path: Path) -> bool:
    return (
        local_path.is_symlink()
        and local_path.resolve(strict=False) == common_path.resolve(strict=False)
    )


def entry_exists_no_follow(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def reject_symlinked_parent(brain_root: Path, path: Path) -> None:
    try:
        relative_parent = path.parent.relative_to(brain_root)
    except ValueError as exc:
        raise SystemExit(f"managed path escapes brain: {path}") from exc
    current = brain_root
    for part in relative_parent.parts:
        current = current / part
        try:
            os.lstat(current)
        except FileNotFoundError:
            return
        if current.is_symlink():
            raise SystemExit(f"managed parent is a symlink: {current}")


def preflight_managed_paths(
    brain_root: Path,
    common: Path,
    wrappers: dict[str, str],
) -> None:
    for local_name, common_name in wrappers.items():
        common_path = common / common_name
        if common_path.exists():
            reject_symlinked_parent(brain_root, brain_root / local_name)
    for local_rel, common_rel in TEMPLATE_SYMLINKS.items():
        common_path = common / common_rel
        if common_path.exists():
            reject_symlinked_parent(brain_root, brain_root / local_rel)


def preflight_managed_content(brain_root: Path, common: Path) -> None:
    preflight_managed_paths(brain_root, common, discover_wrappers(common))


def atomic_symlink_replace(link_path: Path, target: str) -> None:
    temp_path = link_path.with_name(f".{link_path.name}.tmp-{os.getpid()}")
    if entry_exists_no_follow(temp_path):
        raise SystemExit(f"temporary symlink already exists: {temp_path}")
    temp_path.symlink_to(target)
    try:
        os.replace(temp_path, link_path)
    except OSError:
        if entry_exists_no_follow(temp_path):
            temp_path.unlink()
        raise


def apply_managed_content(
    brain_root: Path,
    common: Path,
    reporter: Reporter,
) -> None:
    wrappers = discover_wrappers(common)
    preflight_managed_paths(brain_root, common, wrappers)
    for directory in SCAFFOLD_DIRECTORIES:
        (brain_root / directory).mkdir(parents=True, exist_ok=True)
    for local_name, content in LOCAL_STATE_FILES.items():
        local_path = brain_root / local_name
        if entry_exists_no_follow(local_path):
            continue
        reject_symlinked_parent(brain_root, local_path)
        local_path.write_text(content, encoding="utf-8")
    for local_name, common_name in wrappers.items():
        local_path = brain_root / local_name
        common_path = common / common_name
        if entry_exists_no_follow(local_path) or not common_path.exists():
            continue
        reject_symlinked_parent(brain_root, local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(wrapper_text(local_name, common_name), encoding="utf-8")

    for local_rel, common_rel in TEMPLATE_SYMLINKS.items():
        local_path = brain_root / local_rel
        common_path = common / common_rel
        if not common_path.exists():
            continue
        if is_current_template_symlink(local_path, common_path):
            continue
        if local_path.is_symlink():
            reporter.write(f"  RELINK {local_rel}: {local_path.readlink()}")
            target = via_common_symlink_target(common_rel, local_path, brain_root)
            reject_symlinked_parent(brain_root, local_path)
            atomic_symlink_replace(local_path, target)
            continue
        elif local_path.exists():
            continue
        reject_symlinked_parent(brain_root, local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        target = via_common_symlink_target(common_rel, local_path, brain_root)
        local_path.symlink_to(target)


def managed_content_errors(brain_root: Path, common: Path) -> list[str]:
    errors: list[str] = []
    for local_rel, common_rel in TEMPLATE_SYMLINKS.items():
        local_path = brain_root / local_rel
        common_path = common / common_rel
        if local_path.is_symlink() and not is_current_template_symlink(
            local_path,
            common_path,
        ):
            errors.append(f"{local_rel} does not resolve to {common_rel}")
        elif common_path.exists() and not local_path.exists():
            errors.append(f"{local_rel} is missing")
    return errors

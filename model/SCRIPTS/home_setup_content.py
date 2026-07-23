from __future__ import annotations

from pathlib import Path

from _common import Reporter
from brain_state import COMMON_LINK_NAME

WRAPPERS = {
    "AGENTS.md": "AGENTS.common.md",
    "BRAIN.md": "BRAIN.common.md",
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


def wrapper_text(local_name: str, common_name: str) -> str:
    title = Path(local_name).stem
    return (
        f"# {title}\n\n"
        f"This brain follows the shared model in `_COMMON/{common_name}`.\n"
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


def apply_managed_content(
    brain_root: Path,
    common: Path,
    reporter: Reporter,
) -> None:
    task_type_wrappers = discover_task_type_wrappers(common)
    combined_wrappers = list(WRAPPERS.items()) + list(task_type_wrappers.items())
    for local_name, common_name in combined_wrappers:
        local_path = brain_root / local_name
        common_path = common / common_name
        if local_path.exists() or not common_path.exists():
            continue
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
            local_path.unlink()
        elif local_path.exists():
            continue
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

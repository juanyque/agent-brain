#!/usr/bin/env python3
"""Attach an Obsidian vault to obsidian-vault-common safely.

Dry-run by default. Pass --apply to create the _COMMON symlink and missing local
wrapper files. Existing local files are never overwritten.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

COMMON_LINK_NAME = "_COMMON"
STAGING_DIR_NAME = "_STAGING"
AGENTS_DIR_NAME = "_AGENTS"
OPERATIONAL_TOP_LEVEL_DIRS = {COMMON_LINK_NAME, STAGING_DIR_NAME, AGENTS_DIR_NAME}

# Content-level top-level directories (created on-demand, not during initial setup):
# JOURNAL, WIP, MEMORY, ARCHIVED, BACKLOG, INBOX, REPORTS, QUARANTINE, TEMPLATES, SCRIPTS
# See VAULT.common.md § "Information maturity model" for the complete inventory.

# External agent runtime homes scanned for symlinks pointing into the vault.
# When such symlinks are found, the vault-internal top-level directories they
# target are moved into `_AGENTS/<name>/` instead of `_STAGING/`.
RUNTIME_HOMES = [
    Path("~/.agents"),
    Path("~/.claude"),
    Path("~/.codex"),
]

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

RUNTIME_CANDIDATES = [
    ("Agents", Path("~/.agents/skills")),
    ("Claude", Path("~/.claude/skills")),
    ("Codex", Path("~/.codex/skills")),
]


from _common import Reporter, build_command_string  # noqa: E402  (lives next to this script)


def resolve_common_root(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def wrapper_text(local_name: str, common_name: str) -> str:
    # `local_name` may include a folder prefix (e.g. `TASK_TYPES/foo.md`) — use
    # the file stem so the H1 stays clean (`foo`, not `TASK_TYPES/foo`).
    title = Path(local_name).stem
    return (
        f"# {title}\n\n"
        f"This vault follows the shared model in `_COMMON/{common_name}`.\n"
    )


def discover_task_type_wrappers(common: Path) -> dict[str, str]:
    """Build `{local_name: common_name}` for every common task-type.

    Scans `_COMMON/TASK_TYPES/*.common.md` and derives the vault-local
    wrapper path `TASK_TYPES/<basename-without-.common>.md`. Includes the
    catalog (`TASK_TYPES.common.md` → `TASK_TYPES.md`) — the vault's index
    is a wrapper too, same as `JOBS.md`. Returns empty dict when the common
    directory does not exist.
    """
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
    command = [
        sys.executable,
        str(common / "SKILLS" / "obsidian" / "scripts" / "cleanup_ds_store.py"),
        "--vault-root",
        str(vault),
    ]
    if applied:
        command.append("--apply")
    return command


def run_cleanup_ds_store(
    common: Path, vault: Path, applied: bool, reporter: Reporter
) -> None:
    """Invoke the .DS_Store sweep utility before reading vault state.

    Removing macOS `.DS_Store` files first ensures `cleanup_empty_dirs_recursively`
    sees true emptiness — a dir containing only `.DS_Store` would otherwise look
    populated.
    """
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
    """Remove every recursively-empty visible directory below the vault root.

    git does not track empty directories, so an undo (e.g. `git reset --hard`)
    that reverts files moved into `_STAGING/`, `_AGENTS/`, `WIP/`, etc. leaves
    those directories behind as empty shells. They confuse later state checks
    (e.g. `staging_status` reports "has-content" for a tree that has only
    empty subdirs). This sweep removes them before any other state inspection.

    Walks bottom-up so deeply nested empty leaves are removed first, letting
    their now-empty parents be removed in the same pass. Symlinks are never
    followed or removed. Top-level directories whose name starts with `.`
    (e.g. `.git`, `.obsidian`, `.WIP_<timestamp>` in-flight) are skipped
    entirely — they are runtime-managed or hidden by convention.
    """
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
        # Path is (would-be-)empty when every current child is already slated
        # for removal. Tracking removed_set lets the dry-run preview cascade
        # parents correctly without actually mutating the filesystem.
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


def git_mv_to_agents(
    vault: Path,
    mapping: dict[str, list[Path]],
    reporter: Reporter,
    dry_run: bool,
) -> list[str]:
    """Move runtime-tied vault top-level dirs into `_AGENTS/<name>/`.

    Returns the names that were (or would be) moved. _AGENTS/ is created
    on-demand. Existing destinations are skipped, not overwritten.
    """
    if not mapping:
        return []
    agents = vault / AGENTS_DIR_NAME
    if agents.exists() and not agents.is_dir():
        reporter.write(
            f"  {AGENTS_DIR_NAME}: exists but is not a directory, skipping _AGENTS move"
        )
        return []

    moved: list[str] = []
    reporter.write(f"  runtime-tied dirs to move into {AGENTS_DIR_NAME}/:")
    if not dry_run and not agents.exists():
        agents.mkdir()

    for name in sorted(mapping):
        src = vault / name
        dest = agents / name
        if dest.exists():
            if src.exists():
                reporter.write(
                    f"    {name}: WARNING — both vault root and {AGENTS_DIR_NAME}/{name} contain a copy; "
                    f"manual reconciliation needed, leaving both untouched"
                )
                # Intentionally NOT adding to `moved`: external symlinks must keep pointing
                # to whatever they pointed to until the user reconciles the two copies.
                # Adding to `moved` would let rewrite_external_symlinks re-point them at
                # potentially stale _AGENTS content.
                continue
            reporter.write(
                f"    {name}: already at {AGENTS_DIR_NAME}/{name} (source absent), skipping"
            )
            moved.append(name)
            continue
        if not src.exists():
            reporter.write(f"    {name}: source not found at vault root, skipping")
            continue
        reporter.write(f"    {name} -> {AGENTS_DIR_NAME}/{name}")
        if not dry_run:
            result = subprocess.run(
                ["git", "mv", name, f"{AGENTS_DIR_NAME}/{name}"],
                cwd=vault,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                reporter.write(f"      WARNING: git mv failed: {result.stderr.strip()}")
                continue
        moved.append(name)
    if dry_run:
        reporter.write(f"  (dry-run: no files moved)")
    return moved


def rewrite_external_symlinks(
    vault: Path,
    mapping: dict[str, list[Path]],
    moved_names: list[str],
    reporter: Reporter,
    dry_run: bool,
    timestamp: str,
) -> list[dict]:
    """Backup each detected external symlink and re-point it under _AGENTS/.

    Only symlinks whose owning top-level dir is in `moved_names` are rewritten.
    Returns one record per rewritten symlink with link/old_target/new_target/backup
    so callers can render a migration doc.
    """
    if not mapping:
        return []
    vault_resolved = vault.resolve()
    records: list[dict] = []
    moved_set = set(moved_names)

    reporter.write("  external symlinks to rewrite:")
    any_rewrite = False
    for name, links in sorted(mapping.items()):
        if name not in moved_set:
            continue
        for link in links:
            try:
                old_target = link.resolve(strict=False)
                rel = old_target.relative_to(vault_resolved)
            except (OSError, RuntimeError, ValueError):
                continue
            new_target = vault / AGENTS_DIR_NAME / rel
            backup = link.with_name(link.name + f".bak.{timestamp}")
            records.append(
                {
                    "link": link,
                    "old_target": old_target,
                    "new_target": new_target,
                    "backup": backup,
                }
            )
            any_rewrite = True
            reporter.write(f"    {link}")
            reporter.write(f"      old target: {old_target}")
            reporter.write(f"      new target: {new_target}")
            reporter.write(f"      backup:     {backup}")
            if not dry_run:
                link.rename(backup)
                link.symlink_to(new_target)
    if not any_rewrite:
        reporter.write("    (none)")
    if dry_run and any_rewrite:
        reporter.write(f"  (dry-run: no symlinks rewritten)")
    return records


def write_migration_doc(
    vault: Path,
    records: list[dict],
    reporter: Reporter,
    dry_run: bool,
    timestamp: str,
) -> Path | None:
    """Write a per-migration WIP doc describing rewritten symlinks and cleanup.

    The doc is initially written to `vault/.WIP_<timestamp>/` (a dotfile dir at
    the vault root) so it is excluded by `collect_movable_items` and survives
    the subsequent staging move. After staging, `promote_migration_doc`
    renames the temp dir to canonical `WIP/`.
    """
    if not records:
        return None
    date_part = timestamp.split("T", 1)[0]
    final_path = vault / "WIP" / f"AGENTS_MIGRATION.{date_part}.md"
    reporter.write(f"  migration doc: {final_path}")
    if dry_run:
        return final_path
    temp_dir = vault / f".WIP_{timestamp}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"AGENTS_MIGRATION.{date_part}.md"
    lines: list[str] = []
    lines.append(f"# Agents migration — {date_part}")
    lines.append("")
    lines.append(
        f"`vault_setup.py` detected external symlinks pointing into this vault and moved"
    )
    lines.append(
        f"the affected top-level directories into `{AGENTS_DIR_NAME}/`. The external"
    )
    lines.append("symlinks have been re-pointed to the new locations. The original symlinks")
    lines.append("are preserved as `.bak.<timestamp>` files so the migration is reversible.")
    lines.append("")
    lines.append("## Rewritten symlinks")
    lines.append("")
    for rec in records:
        lines.append(f"- `{rec['link']}`")
        lines.append(f"  - old target: `{rec['old_target']}`")
        lines.append(f"  - new target: `{rec['new_target']}`")
        lines.append(f"  - backup:     `{rec['backup']}`")
        lines.append("")
    lines.append("## Cleanup")
    lines.append("")
    lines.append(
        "After confirming that the new symlinks resolve correctly, remove the backups:"
    )
    lines.append("")
    lines.append("```bash")
    for rec in records:
        lines.append(f"rm {shlex.quote(str(rec['backup']))}")
    lines.append("```")
    lines.append("")
    temp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return final_path


def promote_migration_doc(
    vault: Path,
    timestamp: str,
    reporter: Reporter,
    dry_run: bool,
) -> None:
    """Promote the temp `.WIP_<timestamp>/` dir to canonical `WIP/`.

    No-op when the temp dir does not exist (dry-run, or no records written).
    If `WIP/` already exists at the vault root (unexpected post-staging),
    merge files preserving any existing destination names.
    """
    temp_dir = vault / f".WIP_{timestamp}"
    if not temp_dir.exists():
        return
    final_dir = vault / "WIP"
    if dry_run:
        reporter.write(f"  promote: {temp_dir.name}/ -> WIP/")
        return
    if not final_dir.exists():
        temp_dir.rename(final_dir)
        reporter.write(f"  promoted: {temp_dir.name}/ -> WIP/")
        return
    for item in temp_dir.iterdir():
        dest = final_dir / item.name
        if dest.exists():
            reporter.write(
                f"  WARNING: WIP/{item.name} already exists; "
                f"temp version left at {item} for manual review"
            )
            continue
        item.rename(dest)
    try:
        temp_dir.rmdir()
        reporter.write(f"  merged: {temp_dir.name}/ into existing WIP/")
    except OSError:
        reporter.write(
            f"  partial merge: {temp_dir.name}/ not empty after merge "
            f"(conflicts left for manual review)"
        )


def git_mv_to_staging(
    vault: Path,
    reporter: Reporter,
    dry_run: bool,
    exclude_names: set[str] | None = None,
) -> None:
    staging = vault / STAGING_DIR_NAME
    status, _count = staging_status(vault)

    if status == "has-content":
        reporter.write(f"  {STAGING_DIR_NAME}: already exists with content, skipping")
        return

    excluded = exclude_names or set()
    items = [p for p in collect_movable_items(vault) if p.name not in excluded]
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



def relative_symlink_target(source: Path, link_path: Path) -> str:
    return os.path.relpath(source.resolve(), start=link_path.parent.resolve())


def via_common_symlink_target(common_rel: str, link_path: Path, vault: Path) -> str:
    """Compute a relative symlink target that resolves through the _COMMON link.

    Centralizes vault-to-common indirection through a single symlink (_COMMON).
    If the common directory ever moves, only _COMMON needs updating; per-resource
    symlinks (templates, etc.) keep working unchanged.

    Example: a template at `vault/TEMPLATES/Issue Template.md` pointing at
    `TEMPLATES/TEMPLATE.issue.common.md` resolves to
    `../_COMMON/TEMPLATES/TEMPLATE.issue.common.md`.
    """
    rel = link_path.relative_to(vault)
    depth = len(rel.parts) - 1
    prefix = ("../" * depth) if depth > 0 else ""
    return f"{prefix}{COMMON_LINK_NAME}/{common_rel}"


def link_status(vault: Path, common: Path) -> tuple[str, str]:
    link_path = vault / COMMON_LINK_NAME
    desired = relative_symlink_target(common, link_path)

    if not link_path.exists() and not link_path.is_symlink():
        return "missing", desired
    if not link_path.is_symlink():
        return "conflict-not-symlink", desired
    if link_path.resolve() == common.resolve():
        return "ok", desired
    return "conflict-wrong-target", desired


def discover_runtimes(extra_runtimes: list[str] | None) -> list[Path]:
    runtimes: list[Path] = []
    for _label, raw_runtime in RUNTIME_CANDIDATES:
        runtime = raw_runtime.expanduser()
        if runtime.exists() or runtime.parent.exists():
            runtimes.append(runtime)
    for raw_runtime in extra_runtimes or []:
        runtimes.append(Path(raw_runtime).expanduser())
    unique: list[Path] = []
    seen: set[Path] = set()
    for runtime in runtimes:
        resolved_parent = runtime.parent.resolve() if runtime.parent.exists() else runtime.parent
        key = resolved_parent / runtime.name
        if key in seen:
            continue
        seen.add(key)
        unique.append(runtime)
    return unique


def staging_status(vault: Path) -> tuple[str, int]:
    """Return (status, item_count) for _STAGING in the vault.

    status is one of: "missing", "empty", "has-content".
    """
    staging = vault / STAGING_DIR_NAME
    if not staging.is_dir():
        return "missing", 0
    items = [p for p in staging.iterdir() if p.name != ".git"]
    return ("empty" if not items else "has-content"), len(items)


def collect_movable_items(vault: Path) -> list[Path]:
    return sorted(
        p for p in vault.iterdir()
        if not p.name.startswith(".") and p.name not in OPERATIONAL_TOP_LEVEL_DIRS
    )


def discover_runtime_homes(extra_homes: list[str] | None) -> list[Path]:
    """Return runtime homes that exist on disk, plus user-provided extras.

    Non-existent paths are skipped silently for built-in defaults; user-provided
    paths that do not exist are still returned so the caller can warn.
    """
    homes: list[Path] = []
    for raw in RUNTIME_HOMES:
        home = raw.expanduser()
        if home.is_dir():
            homes.append(home)
    for raw in extra_homes or []:
        homes.append(Path(raw).expanduser())
    seen: set[Path] = set()
    unique: list[Path] = []
    for home in homes:
        try:
            key = home.resolve()
        except OSError:
            key = home
        if key in seen:
            continue
        seen.add(key)
        unique.append(home)
    return unique


def _iter_symlinks(root: Path) -> Iterator[Path]:
    """Yield every symlink found under root, no depth limit, without following them."""
    try:
        entries = list(root.iterdir())
    except (OSError, PermissionError):
        return
    for entry in entries:
        try:
            if entry.is_symlink():
                yield entry
                continue
            if entry.is_dir():
                yield from _iter_symlinks(entry)
        except OSError:
            continue


def detect_runtime_tied_dirs(
    vault: Path, runtime_homes: list[Path]
) -> dict[str, list[Path]]:
    """Map vault top-level dir name → external symlinks resolving into it.

    Walks each runtime home and inspects every symlink it contains. Symlinks
    whose target resolves inside the vault contribute their top-level vault
    directory to the result. Broken symlinks (target does not exist) are
    skipped — typically `.bak.<timestamp>` records of previous migrations
    pointing to moved-away locations. Operational dirs (_COMMON, _STAGING,
    _AGENTS) and dotfile top-level dirs (e.g. .git, .obsidian) are also
    ignored — they must never be moved by this script.
    """
    vault_resolved = vault.resolve()
    mapping: dict[str, list[Path]] = {}
    for home in runtime_homes:
        if not home.is_dir():
            continue
        for link in _iter_symlinks(home):
            try:
                target = link.resolve(strict=False)
            except (OSError, RuntimeError):
                continue
            if not target.exists():
                continue
            try:
                rel = target.relative_to(vault_resolved)
            except ValueError:
                continue
            parts = rel.parts
            if not parts:
                continue
            top = parts[0]
            if top in OPERATIONAL_TOP_LEVEL_DIRS:
                continue
            if top.startswith("."):
                continue
            mapping.setdefault(top, []).append(link)
    return mapping


def skill_setup_command(common: Path, runtime: Path, skill: str, applied: bool) -> list[str]:
    command = [
        sys.executable,
        str(common / "SCRIPTS" / "skill_setup.py"),
        "--common",
        str(common),
        "--runtime",
        str(runtime),
        "--skill",
        skill,
    ]
    if applied:
        command.append("--apply")
    return command


def run_skill_setup(common: Path, runtime: Path, skill: str, applied: bool, reporter: Reporter) -> None:
    command = skill_setup_command(common, runtime, skill, applied)
    reporter.write("")
    reporter.write("# Runtime skill setup")
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.stdout:
        for line in result.stdout.rstrip().splitlines():
            reporter.write(line)
    if result.stderr:
        for line in result.stderr.rstrip().splitlines():
            reporter.write(f"STDERR: {line}")
    if result.returncode != 0:
        raise SystemExit(f"skill-setup failed with exit code {result.returncode}")


def run_skill_setups(common: Path, runtimes: list[Path], skill: str, applied: bool, reporter: Reporter) -> None:
    if not runtimes:
        reporter.write("")
        reporter.write("# Runtime skill setup")
        reporter.write("No supported runtime directories were detected. Skipping skill setup.")
        return
    for runtime in runtimes:
        run_skill_setup(common, runtime, skill, applied=applied, reporter=reporter)


def print_plan(
    vault: Path,
    common: Path,
    reporter: Reporter,
    applied: bool,
    command_string: str,
    skip_skill: bool,
    skip_full_reorder: bool,
    runtimes: list[Path],
    runtime_homes: list[Path],
    runtime_mapping: dict[str, list[Path]],
    skill: str,
) -> None:
    link_st, desired = link_status(vault, common)
    reporter.write("# Vault setup")
    reporter.write("")
    reporter.write(f"mode: {'apply' if applied else 'dry-run'}")
    reporter.write(f"command: {command_string}")
    reporter.write(f"vault: {vault}")
    reporter.write(f"common: {common}")
    reporter.write(f"{COMMON_LINK_NAME}: {link_st} -> {desired}")

    reporter.write("runtime homes scanned:")
    if runtime_homes:
        for home in runtime_homes:
            existence = "exists" if home.is_dir() else "missing"
            reporter.write(f"  {home} ({existence})")
    else:
        reporter.write("  (none)")

    if link_st != "ok" and not skip_full_reorder:
        if runtime_mapping:
            reporter.write(f"{AGENTS_DIR_NAME}: {len(runtime_mapping)} runtime-tied dir(s) detected")
            for name, links in sorted(runtime_mapping.items()):
                reporter.write(f"  {name} (referenced by {len(links)} external symlink(s))")
        else:
            reporter.write(f"{AGENTS_DIR_NAME}: no runtime-tied dirs detected")
        stg_status, stg_count = staging_status(vault)
        reporter.write(f"{STAGING_DIR_NAME}: {stg_status}" + (f" ({stg_count} items)" if stg_count else ""))
        if stg_status != "has-content":
            items = [p for p in collect_movable_items(vault) if p.name not in runtime_mapping]
            reporter.write(f"  {len(items)} non-hidden items will be moved to {STAGING_DIR_NAME}/")
    elif link_st != "ok" and skip_full_reorder:
        reporter.write(f"{AGENTS_DIR_NAME}: skipped by --skip-full-reorder")
        reporter.write(f"{STAGING_DIR_NAME}: skipped by --skip-full-reorder")
    elif link_st == "ok" and runtime_mapping:
        reporter.write(
            f"{AGENTS_DIR_NAME}: {len(runtime_mapping)} runtime-tied dir(s) detected, "
            f"but vault is already attached"
        )
        for name, links in sorted(runtime_mapping.items()):
            reporter.write(f"  {name} (referenced by {len(links)} external symlink(s))")
        reporter.write(
            f"  Re-runs do not auto-migrate. To migrate manually: "
            f"git mv vault/<name> vault/{AGENTS_DIR_NAME}/<name>, then re-point each external symlink."
        )

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
    reporter.write("runtime skill setup:")
    if skip_skill:
        reporter.write("  skipped by --skip-skill")
    elif runtimes:
        for runtime in runtimes:
            reporter.write(
                "  will run: "
                + " ".join(shlex.quote(part) for part in skill_setup_command(common, runtime, skill, applied))
            )
    else:
        reporter.write("  no supported runtime directories detected")
    reporter.write("next steps:")
    reporter.write("  1. Open the vault or connect from another project with /obsidian.")
    reporter.write("  2. Start guided vault standardization with: /obsidian init")


def apply(
    vault: Path,
    common: Path,
    skip_full_reorder: bool,
    runtime_mapping: dict[str, list[Path]],
    timestamp: str,
    reporter: Reporter,
) -> None:
    status, desired = link_status(vault, common)

    if status == "missing" and not skip_full_reorder:
        moved = git_mv_to_agents(vault, runtime_mapping, reporter, dry_run=False)
        records = rewrite_external_symlinks(
            vault, runtime_mapping, moved, reporter, dry_run=False, timestamp=timestamp
        )
        write_migration_doc(vault, records, reporter, dry_run=False, timestamp=timestamp)
        git_mv_to_staging(
            vault, reporter, dry_run=False, exclude_names=set(runtime_mapping)
        )
        promote_migration_doc(vault, timestamp, reporter, dry_run=False)

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
        # Ensure the parent directory exists (TASK_TYPES/ may not exist on
        # first attach for vaults that did not previously use task-types).
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
    parser = argparse.ArgumentParser(description="Attach a vault to obsidian-vault-common")
    parser.add_argument("--vault", required=True, help="Path to the vault root")
    parser.add_argument("--common", help="Path to obsidian-vault-common. Defaults to this script's repo root.")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Default is dry-run.")
    parser.add_argument("--skip-skill", action="store_true", help="Do not run runtime skill setup.")
    parser.add_argument("--runtime", action="append", help="Additional runtime skills directory. Can be passed more than once.")
    parser.add_argument("--runtime-home", action="append", help="Additional external runtime home (e.g. ~/.foo) to scan for symlinks pointing into the vault. The scan walks the home recursively without following symlinks; prefer narrow paths (e.g. a dotfile dir under $HOME) over generic ones like $HOME itself. Can be passed more than once.")
    parser.add_argument("--skill", default="obsidian", help="Skill name to install in detected runtimes.")
    parser.add_argument("--skip-full-reorder", action="store_true", help="Skip creating _AGENTS/_STAGING and moving vault content. Use when _COMMON does not exist yet but the user does not want a full reorganization.")
    args = parser.parse_args()
    reporter = Reporter(Path(__file__).with_suffix(".log"))
    command_string = build_command_string()

    try:
        vault = Path(args.vault).expanduser().resolve()
        common = resolve_common_root(args.common)
        runtimes = discover_runtimes(args.runtime)
        runtime_homes = discover_runtime_homes(args.runtime_home)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

        if not vault.is_dir():
            raise SystemExit(f"Vault directory not found: {vault}")
        if not common.is_dir():
            raise SystemExit(f"Common directory not found: {common}")

        # Pre-cleanup before reading vault state. Gated by --skip-full-reorder:
        # if the user explicitly opted out of reordering, leave the vault alone.
        # Order matters: .DS_Store removal must run before the empty-dir sweep
        # so dirs holding only .DS_Store are detected as empty afterwards.
        if not args.skip_full_reorder:
            run_cleanup_ds_store(common, vault, applied=args.apply, reporter=reporter)
            cleanup_empty_dirs_recursively(vault, reporter, dry_run=not args.apply)

        runtime_mapping = detect_runtime_tied_dirs(vault, runtime_homes)

        print_plan(
            vault,
            common,
            reporter=reporter,
            applied=args.apply,
            command_string=command_string,
            skip_skill=args.skip_skill,
            skip_full_reorder=args.skip_full_reorder,
            runtimes=runtimes,
            runtime_homes=runtime_homes,
            runtime_mapping=runtime_mapping,
            skill=args.skill,
        )
        if not args.apply:
            link_st, _ = link_status(vault, common)
            if link_st != "ok" and not args.skip_full_reorder:
                reporter.write("")
                moved = git_mv_to_agents(vault, runtime_mapping, reporter, dry_run=True)
                records = rewrite_external_symlinks(
                    vault, runtime_mapping, moved, reporter, dry_run=True, timestamp=timestamp
                )
                write_migration_doc(vault, records, reporter, dry_run=True, timestamp=timestamp)
                git_mv_to_staging(vault, reporter, dry_run=True, exclude_names=set(runtime_mapping))
                promote_migration_doc(vault, timestamp, reporter, dry_run=True)
            if not args.skip_skill:
                run_skill_setups(common, runtimes, args.skill, applied=False, reporter=reporter)
            reporter.write("Dry run only. Re-run with --apply to create missing safe items.")
            reporter.flush()
            return 0

        apply(
            vault,
            common,
            skip_full_reorder=args.skip_full_reorder,
            runtime_mapping=runtime_mapping,
            timestamp=timestamp,
            reporter=reporter,
        )
        errors = validate(vault, common)
        if errors:
            for error in errors:
                reporter.write(f"ERROR: {error}")
            reporter.flush()
            return 1
        if not args.skip_skill:
            run_skill_setups(common, runtimes, args.skill, applied=True, reporter=reporter)
        reporter.write("Vault setup completed successfully.")
        reporter.flush()
        return 0
    except SystemExit as exc:
        reporter.write(f"ERROR: {exc}")
        reporter.flush()
        raise


if __name__ == "__main__":
    raise SystemExit(main())

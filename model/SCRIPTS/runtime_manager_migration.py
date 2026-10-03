#!/usr/bin/env python3
"""Old-layout migration helpers for :mod:`runtime_manager`.

Keeping migration separate makes the runtime manager's normal direction-A/B
wiring easier to audit without changing its public function names.
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Iterator
from pathlib import Path

from _common import Reporter
from brain_state import AGENTS_DIR_NAME, OPERATIONAL_TOP_LEVEL_DIRS


def _iter_symlinks(root: Path) -> Iterator[Path]:
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
    brain_root: Path, runtime_homes: list[Path]
) -> dict[str, list[Path]]:
    brain_resolved = brain_root.resolve()
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
                rel = target.relative_to(brain_resolved)
            except ValueError:
                continue
            parts = rel.parts
            if not parts:
                continue
            top = parts[0]
            if top in OPERATIONAL_TOP_LEVEL_DIRS or top.startswith("."):
                continue
            mapping.setdefault(top, []).append(link)
    return mapping


def git_mv_to_agents(
    brain_root: Path,
    mapping: dict[str, list[Path]],
    reporter: Reporter,
    dry_run: bool,
) -> list[str]:
    if not mapping:
        return []
    agents = brain_root / AGENTS_DIR_NAME
    if agents.exists() and not agents.is_dir():
        reporter.write(f"  {AGENTS_DIR_NAME}: exists but is not a directory, skipping")
        return []

    moved: list[str] = []
    reporter.write(f"  runtime-tied dirs to move into {AGENTS_DIR_NAME}/:")
    if not dry_run and not agents.exists():
        agents.mkdir()

    for name in sorted(mapping):
        src = brain_root / name
        dest = agents / name
        if dest.exists():
            if src.exists():
                reporter.write(
                    f"    {name}: WARNING — both root and {AGENTS_DIR_NAME}/{name}; skipping"
                )
                continue
            moved.append(name)
            continue
        if not src.exists():
            continue
        reporter.write(f"    {name} -> {AGENTS_DIR_NAME}/{name}")
        if not dry_run:
            result = subprocess.run(
                ["git", "mv", name, f"{AGENTS_DIR_NAME}/{name}"],
                cwd=brain_root,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                reporter.write(f"      WARNING: git mv failed: {result.stderr.strip()}")
                continue
        moved.append(name)
    if dry_run:
        reporter.write("  (dry-run: no files moved)")
    return moved


def rewrite_external_symlinks(
    brain_root: Path,
    mapping: dict[str, list[Path]],
    moved_names: list[str],
    reporter: Reporter,
    dry_run: bool,
    timestamp: str,
) -> list[dict]:
    if not mapping:
        return []
    brain_resolved = brain_root.resolve()
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
                rel = old_target.relative_to(brain_resolved)
            except (OSError, RuntimeError, ValueError):
                continue
            new_target = brain_root / AGENTS_DIR_NAME / rel
            backup = link.with_name(link.name + f".bak.{timestamp}")
            records.append(
                {"link": link, "old_target": old_target, "new_target": new_target, "backup": backup}
            )
            any_rewrite = True
            reporter.write(f"    {link}")
            reporter.write(f"      old: {old_target}")
            reporter.write(f"      new: {new_target}")
            reporter.write(f"      bak: {backup}")
            if not dry_run:
                link.rename(backup)
                link.symlink_to(new_target)
    if not any_rewrite:
        reporter.write("    (none)")
    if dry_run and any_rewrite:
        reporter.write("  (dry-run: no symlinks rewritten)")
    return records


def write_migration_doc(
    brain_root: Path,
    records: list[dict],
    reporter: Reporter,
    dry_run: bool,
    timestamp: str,
) -> None:
    if not records:
        return
    date_part = timestamp.split("T", 1)[0]
    final_path = brain_root / "WIP" / f"AGENTS_MIGRATION.{date_part}.md"
    reporter.write(f"  migration doc: {final_path}")
    if dry_run:
        return
    temp_dir = brain_root / f".WIP_{timestamp}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"AGENTS_MIGRATION.{date_part}.md"
    lines: list[str] = [
        f"# Agents migration — {date_part}",
        "",
        "runtime_manager detected external symlinks pointing into this brain",
        f"and moved the affected directories into `{AGENTS_DIR_NAME}/`.",
        "",
        "## Rewritten symlinks",
        "",
    ]
    for rec in records:
        lines.extend([
            f"- `{rec['link']}`",
            f"  - old: `{rec['old_target']}`",
            f"  - new: `{rec['new_target']}`",
            f"  - bak: `{rec['backup']}`",
            "",
        ])
    lines.extend([
        "## Cleanup",
        "",
        "After verifying new symlinks resolve, remove backups:",
        "",
        "```bash",
    ])
    for rec in records:
        lines.append(f"rm {shlex.quote(str(rec['backup']))}")
    lines.extend(["```", ""])
    temp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def promote_migration_doc(brain_root: Path, timestamp: str, reporter: Reporter, dry_run: bool) -> None:
    temp_dir = brain_root / f".WIP_{timestamp}"
    if not temp_dir.exists():
        return
    final_dir = brain_root / "WIP"
    if dry_run:
        reporter.write(f"  promote: {temp_dir.name}/ -> WIP/")
        return
    if not final_dir.exists():
        temp_dir.rename(final_dir)
        return
    for item in temp_dir.iterdir():
        dest = final_dir / item.name
        if dest.exists():
            continue
        item.rename(dest)
    try:
        temp_dir.rmdir()
    except OSError as exc:
        reporter.write(f"  WARNING: could not remove temporary migration directory {temp_dir}: {exc}")

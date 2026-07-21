#!/usr/bin/env python3
"""Runtime manager — all runtime wiring for a brain (D21/D26).

Handles: runtime discovery, Direction A (ingest local -> brain _AGENTS/),
Direction B (implant brain -> local via runtime_install.sh), conflict
quarantine (-> INBOX/_RUNTIME/<rt>/), old-layout migration (runtime-tied
dirs -> _AGENTS/), and brain skill linking.

Consults brain_state to avoid touching organized brains unnecessarily.
Dry-run by default. Pass --apply to execute.
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

from brain_state import (  # noqa: E402
    AGENTS_DIR_NAME,
    OPERATIONAL_TOP_LEVEL_DIRS,
    link_status,
)
from _common import Reporter, build_command_string  # noqa: E402

RUNTIME_CONFIGS = {
    "claude": {
        "local_dir": Path("~/.claude"),
        "agents_subdir": "CLAUDE",
        "mappings": [
            ("CLAUDE.runtime.claude.md", "CLAUDE.md"),
            ("settings.json", "settings.json"),
            ("memory", "memory"),
        ],
    },
    "opencode": {
        "local_dir": Path("~/.config/opencode"),
        "agents_subdir": "OPENCODE",
        "mappings": [
            ("AGENTS.runtime.opencode.md", "AGENTS.md"),
            ("opencode.json", "opencode.json"),
            ("oh-my-openagent.json", "oh-my-openagent.json"),
        ],
    },
    "agents": {
        "local_dir": Path("~/.agents"),
        "agents_subdir": "AGENTS",
        "mappings": [
            ("AGENTS.runtime.agents.md", "AGENTS.md"),
        ],
    },
    # Codex discovers user skills in ~/.agents/skills. Its private, user-level
    # config is persisted by the brain without coupling it to the public model.
    "codex": {
        "local_dir": Path("~/.codex"),
        "agents_subdir": "CODEX",
        "mappings": [
            ("AGENTS.runtime.codex.md", "AGENTS.md"),
            ("config.toml", "config.toml"),
        ],
        "skills_dir": Path("~/.agents/skills"),
        "private_targets": {"config.toml"},
    },
}

RUNTIME_HOMES = [Path("~/.agents"), Path("~/.claude"), Path("~/.codex")]
INBOX_RUNTIME_DIR_NAME = "INBOX/_RUNTIME"


def resolve_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_common_root(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def local_dir_for(rt_name: str) -> Path:
    return RUNTIME_CONFIGS[rt_name]["local_dir"].expanduser()


def brain_agents_subdir(brain_root: Path, rt_name: str) -> Path:
    return brain_root / AGENTS_DIR_NAME / RUNTIME_CONFIGS[rt_name]["agents_subdir"]


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


def discover_runtime_homes(extra_homes: list[str] | None) -> list[Path]:
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
    except OSError:
        pass


def run_runtime_install(
    rt_name: str,
    brain_root: Path,
    apply: bool,
    reporter: Reporter,
    assume_target_missing: set[str] | None = None,
    assume_source_present: set[str] | None = None,
) -> None:
    script = Path(__file__).parent / "runtime_install.sh"
    cmd = ["bash", str(script), rt_name, "--brain", str(brain_root)]
    if apply:
        cmd.append("--apply")
    else:
        for target in sorted(assume_target_missing or set()):
            cmd.extend(["--assume-target-missing", target])
        for source in sorted(assume_source_present or set()):
            cmd.extend(["--assume-source-present", source])
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.stdout:
        for line in result.stdout.rstrip().splitlines():
            reporter.write(f"  {line}")
    if result.stderr:
        for line in result.stderr.rstrip().splitlines():
            reporter.write(f"  STDERR: {line}")
    if result.returncode != 0:
        raise SystemExit(f"runtime_install failed for {rt_name} with exit code {result.returncode}")


def ingest_local_to_brain(
    rt_name: str,
    brain_root: Path,
    reporter: Reporter,
    dry_run: bool,
    only_targets: set[str] | None = None,
) -> tuple[set[str], set[str]]:
    config = RUNTIME_CONFIGS[rt_name]
    local_dir = config["local_dir"].expanduser()
    agents_dir = brain_agents_subdir(brain_root, rt_name)

    reporter.write(f"  Direction A: ingest local {local_dir} -> {agents_dir}")
    if not dry_run:
        agents_dir.mkdir(parents=True, exist_ok=True)

    ingested_sources: set[str] = set()
    removed_targets: set[str] = set()
    for brain_source, local_target in config["mappings"]:
        if only_targets is not None and local_target not in only_targets:
            continue
        local_path = local_dir / local_target
        brain_path = agents_dir / brain_source
        if not local_path.exists() and not local_path.is_symlink():
            reporter.write(f"    SKIP {local_target} (not found locally)")
            continue
        if local_path.is_symlink():
            reporter.write(f"    SKIP {local_target} (already a symlink — likely managed)")
            continue
        ingested_sources.add(brain_source)
        removed_targets.add(local_target)
        reporter.write(f"    MOVE {local_target} -> _AGENTS/{config['agents_subdir']}/{brain_source}")
        if not dry_run:
            if local_path.is_dir():
                import shutil
                shutil.copytree(local_path, brain_path)
                shutil.rmtree(local_path)
            else:
                import shutil
                shutil.copy2(local_path, brain_path)
                local_path.unlink()
            if local_target in config.get("private_targets", set()):
                brain_path.chmod(0o600)
            subprocess.run(["git", "add", str(brain_path)], cwd=brain_root, check=False, capture_output=True)
    return ingested_sources, removed_targets


def quarantine_local(
    rt_name: str,
    brain_root: Path,
    reporter: Reporter,
    dry_run: bool,
    only_targets: set[str] | None = None,
) -> set[str]:
    config = RUNTIME_CONFIGS[rt_name]
    local_dir = config["local_dir"].expanduser()
    quarantine_dir = brain_root / INBOX_RUNTIME_DIR_NAME / config["agents_subdir"]

    reporter.write(f"  Conflict: quarantine local {local_dir} -> {quarantine_dir}")
    if not dry_run:
        quarantine_dir.mkdir(parents=True, exist_ok=True)

    quarantined_targets: set[str] = set()
    for brain_source, local_target in config["mappings"]:
        if only_targets is not None and local_target not in only_targets:
            continue
        local_path = local_dir / local_target
        if not local_path.exists() or local_path.is_symlink():
            continue
        quarantined_targets.add(local_target)
        q_path = quarantine_dir / local_target
        reporter.write(f"    QUARANTINE {local_target} -> INBOX/_RUNTIME/{config['agents_subdir']}/{local_target}")
        if not dry_run:
            import shutil
            if local_path.is_dir():
                shutil.copytree(local_path, q_path)
                shutil.rmtree(local_path)
            else:
                shutil.copy2(local_path, q_path)
                local_path.unlink()
            subprocess.run(["git", "add", str(q_path)], cwd=brain_root, check=False, capture_output=True)
    return quarantined_targets


def link_skill(rt_name: str, brain_root: Path, reporter: Reporter, dry_run: bool) -> None:
    repo_root = resolve_repo_root()
    config = RUNTIME_CONFIGS[rt_name]
    local_dir = config["local_dir"].expanduser()
    skills_dir = config.get("skills_dir", local_dir / "skills").expanduser()
    link = skills_dir / "brain"
    target = repo_root / "skills" / "brain"

    if link.is_symlink() and link.resolve() == target.resolve():
        reporter.write(f"  OK    skill brain ({rt_name}) already linked at {link}")
        return
    if link.exists() or link.is_symlink():
        reporter.write(f"  BACKUP {link} (exists, not our symlink)")
        if not dry_run:
            backup = link.with_name(link.name + f".backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
            link.rename(backup)
    reporter.write(f"  LINK  skill brain ({rt_name}): {link} -> {target}")
    if not dry_run:
        skills_dir.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)


def link_shared_memory(brain_root: Path, reporter: Reporter, dry_run: bool) -> None:
    source = brain_root / AGENTS_DIR_NAME / "SHARED" / "memory"
    link = Path("~/.agents/brain-memory").expanduser()

    if not source.is_dir():
        reporter.write(f"  SKIP  shared memory (source missing: {source})")
        return
    if link.is_symlink() and link.resolve() == source.resolve():
        reporter.write(f"  OK    shared memory already linked at {link}")
        return
    if link.exists() or link.is_symlink():
        reporter.write(f"  BACKUP {link} (exists, not our symlink)")
        if not dry_run:
            backup = link.with_name(link.name + f".backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
            link.rename(backup)
    reporter.write(f"  LINK  shared memory: {link} -> {source}")
    if not dry_run:
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(source)


def process_runtime(
    rt_name: str,
    brain_root: Path,
    reporter: Reporter,
    dry_run: bool,
) -> None:
    if rt_name not in RUNTIME_CONFIGS:
        reporter.write(f"  SKIP unknown runtime: {rt_name}")
        return

    config = RUNTIME_CONFIGS[rt_name]
    local_dir = config["local_dir"].expanduser()

    if not config.get("mappings"):
        reporter.write(f"-- runtime: {rt_name} (skill-only) --")
        if local_dir.is_dir():
            link_skill(rt_name, brain_root, reporter, dry_run)
        else:
            reporter.write("  SKIP (local dir not present)")
        return

    reporter.write(f"-- runtime: {rt_name} --")
    brain_rt_dir = brain_agents_subdir(brain_root, rt_name)
    ingest_targets: set[str] = set()
    quarantine_targets: set[str] = set()
    available_sources: set[str] = set()

    for brain_source, local_target in config["mappings"]:
        brain_path = brain_rt_dir / brain_source
        local_path = local_dir / local_target
        brain_present = brain_path.exists() or brain_path.is_symlink()
        local_present = local_path.exists() or local_path.is_symlink()
        local_correct = False
        if local_path.is_symlink() and brain_present:
            try:
                local_correct = local_path.resolve() == brain_path.resolve()
            except OSError:
                local_correct = False

        if brain_present:
            available_sources.add(brain_source)
            if local_present and not local_path.is_symlink():
                quarantine_targets.add(local_target)
            elif local_correct:
                reporter.write(f"  OK    {local_target} already linked")
        elif local_present and not local_path.is_symlink():
            ingest_targets.add(local_target)
        elif local_path.is_symlink():
            reporter.write(
                f"  WARNING {local_target} is a symlink but brain source is missing: {brain_path}"
            )

    ingested_sources: set[str] = set()
    removed_targets: set[str] = set()
    if ingest_targets:
        ingested_sources, removed_targets = ingest_local_to_brain(
            rt_name,
            brain_root,
            reporter,
            dry_run,
            only_targets=ingest_targets,
        )
        available_sources.update(ingested_sources)

    quarantined_targets: set[str] = set()
    if quarantine_targets:
        quarantined_targets = quarantine_local(
            rt_name,
            brain_root,
            reporter,
            dry_run,
            only_targets=quarantine_targets,
        )

    if available_sources:
        if not ingest_targets and not quarantine_targets:
            reporter.write("  Direction B: implant/verify brain -> local")
        run_runtime_install(
            rt_name,
            brain_root,
            apply=not dry_run,
            reporter=reporter,
            assume_target_missing=(removed_targets | quarantined_targets) if dry_run else None,
            assume_source_present=ingested_sources if dry_run else None,
        )
    else:
        reporter.write("  SKIP (no local or brain-managed config found)")

    if local_dir.is_dir() or available_sources:
        link_skill(rt_name, brain_root, reporter, dry_run)
    if rt_name == "codex" and (local_dir.is_dir() or available_sources):
        link_shared_memory(brain_root, reporter, dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description="Runtime manager — wire runtime config for a brain (D21)")
    parser.add_argument("--brain", required=True, help="Path to the brain root")
    parser.add_argument("--common", help="Path to the model root (for repo resolution). Defaults to this script's model/.")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Default is dry-run.")
    parser.add_argument("--runtime", action="append", help="Restrict to a specific runtime (claude, opencode, agents, codex). Can be passed more than once.")
    parser.add_argument("--runtime-home", action="append", help="Additional runtime home to scan for symlinks. Can be passed more than once.")
    args = parser.parse_args()
    reporter = Reporter(Path(__file__).with_suffix(".log"))
    command_string = build_command_string()

    try:
        brain_root = Path(args.brain).expanduser().resolve()
        common = resolve_common_root(args.common)

        if not brain_root.is_dir():
            raise SystemExit(f"Brain directory not found: {brain_root}")

        runtime_homes = discover_runtime_homes(args.runtime_home)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

        reporter.write("# Runtime manager")
        reporter.write(f"mode: {'apply' if args.apply else 'dry-run'}")
        reporter.write(f"command: {command_string}")
        reporter.write(f"brain: {brain_root}")
        reporter.write("")

        if args.runtime:
            runtimes = args.runtime
        else:
            runtimes = list(RUNTIME_CONFIGS.keys())

        link_st, _ = link_status(brain_root, common)
        if link_st != "ok":
            reporter.write(f"_COMMON: {link_st} (runtime wiring may not fully work until home_setup attaches the model)")
            reporter.write("")

        runtime_mapping = detect_runtime_tied_dirs(brain_root, runtime_homes)
        if runtime_mapping and link_st != "ok":
            reporter.write("# Old-layout migration (runtime-tied dirs)")
            moved = git_mv_to_agents(brain_root, runtime_mapping, reporter, dry_run=not args.apply)
            records = rewrite_external_symlinks(
                brain_root, runtime_mapping, moved, reporter, dry_run=not args.apply, timestamp=timestamp
            )
            write_migration_doc(brain_root, records, reporter, dry_run=not args.apply, timestamp=timestamp)
            promote_migration_doc(brain_root, timestamp, reporter, dry_run=not args.apply)
            reporter.write("")

        for rt_name in runtimes:
            process_runtime(rt_name, brain_root, reporter, dry_run=not args.apply)
            reporter.write("")

        reporter.write("Runtime manager completed." if args.apply else "Dry run only. Re-run with --apply to execute.")
        reporter.flush()
        return 0
    except SystemExit as exc:
        reporter.write(f"ERROR: {exc}")
        reporter.flush()
        raise


if __name__ == "__main__":
    raise SystemExit(main())

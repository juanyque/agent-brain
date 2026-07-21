#!/usr/bin/env python3
"""Verify brain-managed runtime wiring after bootstrap apply.

The runtime matrix is imported from runtime_manager so installation and health
checks cannot silently drift apart. This script is read-only.
"""

from __future__ import annotations

import argparse
import stat
from pathlib import Path

from brain_state import AGENTS_DIR_NAME
from runtime_manager import (
    RUNTIME_CONFIGS,
    brain_agents_subdir,
    local_dir_for,
    resolve_repo_root,
)


RUNTIME_LABELS = {
    "claude": "Claude",
    "opencode": "OpenCode",
    "agents": "Agents",
    "codex": "Codex",
}


class HealthCheck:
    def __init__(self) -> None:
        self.failed = False

    def ok(self, label: str) -> None:
        print(f"  OK   {label}")

    def fail(self, label: str, detail: str) -> None:
        print(f"  FAIL {label} ({detail})")
        self.failed = True

    def link(self, label: str, link: Path, target: Path) -> None:
        if not link.is_symlink():
            self.fail(label, f"not a symlink: {link}")
            return
        try:
            actual = link.resolve(strict=True)
            expected = target.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            self.fail(label, f"unresolvable link: {exc}")
            return
        if actual == expected:
            self.ok(label)
        else:
            self.fail(label, f"resolves to {actual}, expected {expected}")


def source_is_managed(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def expand_runtime_path(path: Path, home_root: Path | None = None) -> Path:
    if home_root is None:
        return path.expanduser()
    raw = str(path)
    if raw == "~":
        return home_root
    if raw.startswith("~/"):
        return home_root / raw[2:]
    return path.expanduser()


def check_runtime(
    name: str,
    brain_root: Path,
    check: HealthCheck,
    *,
    home_root: Path | None = None,
    repo_root: Path | None = None,
) -> None:
    if name not in RUNTIME_CONFIGS:
        check.fail(f"runtime {name}", "unsupported runtime")
        return

    config = RUNTIME_CONFIGS[name]
    label = RUNTIME_LABELS.get(name, name)
    local_dir = (
        local_dir_for(name)
        if home_root is None
        else expand_runtime_path(config["local_dir"], home_root)
    )
    brain_dir = brain_agents_subdir(brain_root, name)
    managed_sources: list[tuple[str, str, Path]] = []
    local_mapped_state = False

    for brain_source, local_target in config["mappings"]:
        source = brain_dir / brain_source
        local = local_dir / local_target
        if source_is_managed(source):
            managed_sources.append((brain_source, local_target, source))
        if local.exists() or local.is_symlink():
            local_mapped_state = True

    active = local_dir.is_dir() or bool(managed_sources) or local_mapped_state
    print(f"-- runtime: {name} --")
    if not active:
        print("  SKIP (no local or brain-managed config found)")
        return

    managed_names = {source_name for source_name, _, _ in managed_sources}
    for brain_source, local_target in config["mappings"]:
        source = brain_dir / brain_source
        local = local_dir / local_target
        if brain_source in managed_names:
            if not source.exists():
                check.fail(f"{label} source {brain_source}", f"broken symlink: {source}")
                continue
            check.link(f"{label} {local_target} linked", local, source)
            if local_target in config.get("private_targets", set()):
                mode = stat.S_IMODE(source.stat().st_mode)
                if mode == 0o600:
                    check.ok(f"{label} {local_target} permissions 0600")
                else:
                    check.fail(
                        f"{label} {local_target} permissions",
                        f"{mode:04o}, expected 0600",
                    )
        elif local.exists() or local.is_symlink():
            check.fail(
                f"{label} {local_target}",
                f"local state exists but brain source is missing: {source}",
            )

    skills_dir = expand_runtime_path(
        config.get("skills_dir", local_dir / "skills"), home_root
    )
    check.link(
        f"{label} brain skill linked",
        skills_dir / "brain",
        (repo_root or resolve_repo_root()) / "skills" / "brain",
    )

    if name == "codex":
        shared_memory = brain_root / AGENTS_DIR_NAME / "SHARED" / "memory"
        if shared_memory.is_dir():
            check.link(
                "Codex shared curated memory linked",
                expand_runtime_path(Path("~/.agents/brain-memory"), home_root),
                shared_memory,
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only health check for brain-managed runtime wiring"
    )
    parser.add_argument("--brain", required=True, help="Path to the brain root")
    parser.add_argument(
        "--runtime",
        action="append",
        help="Runtime to verify. Repeat for multiple runtimes; defaults to all supported runtimes.",
    )
    args = parser.parse_args()

    brain_root = Path(args.brain).expanduser().resolve()
    if not brain_root.is_dir():
        print(f"  FAIL brain directory not found ({brain_root})")
        return 1

    runtimes = args.runtime or list(RUNTIME_CONFIGS)
    seen: set[str] = set()
    check = HealthCheck()
    for name in runtimes:
        if name in seen:
            continue
        seen.add(name)
        check_runtime(name, brain_root, check)

    return 1 if check.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

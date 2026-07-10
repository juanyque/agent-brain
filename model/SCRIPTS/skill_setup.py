#!/usr/bin/env python3
"""Install shared Obsidian-vault-common skills into an agent runtime with symlinks.

The script is dry-run by default. Pass --apply to create or repair links.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

MARKER_NAME = ".obsidian-vault-common-link.json"


from _common import Reporter, build_command_string  # noqa: E402  (lives next to this script)


def resolve_common_root(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def load_marker(path: Path) -> dict | None:
    marker = path / MARKER_NAME
    if not marker.exists():
        return None
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid marker JSON: {marker}: {exc}") from exc


def relative_to_common(path: Path, common_root: Path) -> str:
    return str(path.resolve().relative_to(common_root.resolve()))


def planned_links(common_root: Path, skill: str) -> tuple[Path, dict[str, Path]]:
    source_dir = common_root / "SKILLS" / skill
    if not source_dir.is_dir():
        raise SystemExit(f"Skill source directory not found: {source_dir}")

    common_skill = source_dir / f"SKILL.{skill}.common.md"
    plain_skill = source_dir / "SKILL.md"

    links: dict[str, Path] = {}
    if common_skill.is_file():
        links["SKILL.md"] = common_skill
        for child in sorted(source_dir.iterdir()):
            if child.name == common_skill.name or child.name == MARKER_NAME:
                continue
            if child.suffix == ".md":
                continue
            links[child.name] = child
        return source_dir, links

    if plain_skill.is_file():
        links[skill] = source_dir
        return source_dir, links

    raise SystemExit(
        f"No skill entrypoint found for {skill}. Expected {common_skill} or {plain_skill}."
    )


def ensure_safe_target(target_dir: Path, force_adopt: bool) -> dict | None:
    if not target_dir.exists():
        return None
    if not target_dir.is_dir() or target_dir.is_symlink():
        raise SystemExit(f"Refusing to modify non-directory target: {target_dir}")

    marker = load_marker(target_dir)
    if marker is not None:
        return marker

    if force_adopt:
        return None

    raise SystemExit(
        "Refusing to modify existing skill directory without ownership marker: "
        f"{target_dir}\nUse --force-adopt if this directory should be managed by obsidian-vault-common."
    )


def remove_existing(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if path.is_dir():
        shutil.rmtree(path)


def link_matches(link_path: Path, source: Path) -> bool:
    if not link_path.is_symlink():
        return False
    return link_path.resolve() == source.resolve()


def make_relative_symlink(source: Path, link_path: Path) -> None:
    rel_source = os.path.relpath(source.resolve(), start=link_path.parent.resolve())
    link_path.symlink_to(rel_source, target_is_directory=source.is_dir())


def build_marker(common_root: Path, source_dir: Path, skill: str, links: dict[str, Path]) -> dict:
    return {
        "managed_by": "obsidian-vault-common",
        "skill": skill,
        "common_root": str(common_root.resolve()),
        "source_skill_dir": str(source_dir.resolve()),
        "links": {name: relative_to_common(source, common_root) for name, source in links.items()},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def print_plan(target_dir: Path, links: dict[str, Path], marker_exists: bool, reporter: Reporter, applied: bool, command_string: str) -> None:
    reporter.write("# Skill setup")
    reporter.write("")
    reporter.write(f"mode: {'apply' if applied else 'dry-run'}")
    reporter.write(f"command: {command_string}")
    reporter.write(f"target: {target_dir}")
    reporter.write(f"marker: {'present' if marker_exists else 'will be created'}")
    reporter.write("links:")
    for name, source in links.items():
        reporter.write(f"  {target_dir / name} -> {source}")


def apply_links(target_dir: Path, common_root: Path, source_dir: Path, skill: str, links: dict[str, Path]) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)

    for name, source in links.items():
        link_path = target_dir / name
        if link_matches(link_path, source):
            continue
        if link_path.exists() or link_path.is_symlink():
            remove_existing(link_path)
        make_relative_symlink(source, link_path)

    marker = build_marker(common_root, source_dir, skill, links)
    (target_dir / MARKER_NAME).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")


def validate(target_dir: Path, links: dict[str, Path]) -> list[str]:
    errors = []
    for name, source in links.items():
        link_path = target_dir / name
        if not link_path.is_symlink():
            errors.append(f"not a symlink: {link_path}")
        elif link_path.resolve() != source.resolve():
            errors.append(f"wrong target: {link_path} -> {link_path.resolve()} expected {source.resolve()}")
    if not (target_dir / MARKER_NAME).is_file():
        errors.append(f"missing marker: {target_dir / MARKER_NAME}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Install common skills into an agent runtime using symlinks")
    parser.add_argument("--common", help="Path to obsidian-vault-common. Defaults to this script's repo root.")
    parser.add_argument("--runtime", required=True, help="Runtime skills directory, e.g. ~/.agents/skills")
    parser.add_argument("--skill", default="obsidian", help="Skill name to install")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Default is dry-run.")
    parser.add_argument("--force-adopt", action="store_true", help="Adopt an existing unmarked runtime skill directory")
    args = parser.parse_args()
    reporter = Reporter(Path(__file__).with_suffix(".log"))
    command_string = build_command_string()

    try:
        common_root = resolve_common_root(args.common)
        runtime_root = Path(args.runtime).expanduser().resolve()
        target_dir = runtime_root / args.skill

        source_dir, links = planned_links(common_root, args.skill)
        existing_marker = ensure_safe_target(target_dir, args.force_adopt)

        print_plan(target_dir, links, marker_exists=existing_marker is not None, reporter=reporter, applied=args.apply, command_string=command_string)

        if not args.apply:
            reporter.write("Dry run only. Re-run with --apply to create or repair links.")
            reporter.flush()
            return 0

        apply_links(target_dir, common_root, source_dir, args.skill, links)
        errors = validate(target_dir, links)
        if errors:
            for error in errors:
                reporter.write(f"ERROR: {error}")
            reporter.flush()
            return 1

        reporter.write("Skill links installed successfully.")
        reporter.flush()
        return 0
    except SystemExit as exc:
        reporter.write(f"ERROR: {exc}")
        reporter.flush()
        raise


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class EntryStat:
    exists: bool
    is_dir: bool
    is_file: bool
    is_symlink: bool


def lstat_entry(path: Path) -> EntryStat:
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return EntryStat(exists=False, is_dir=False, is_file=False, is_symlink=False)
    return EntryStat(
        exists=True,
        is_dir=stat.S_ISDIR(mode),
        is_file=stat.S_ISREG(mode),
        is_symlink=stat.S_ISLNK(mode),
    )


def readlink_text(path: Path) -> str:
    return os.readlink(path)


def symlinked_parent(brain_root: Path, managed_path: Path) -> Path | None:
    relative_parent = managed_path.parent.relative_to(brain_root)
    current = brain_root
    for part in relative_parent.parts:
        current = current / part
        entry = lstat_entry(current)
        if not entry.exists:
            return None
        if entry.is_symlink:
            return current
    return None


def walk_no_follow(root: Path) -> Iterator[Path]:
    for parent, dirs, files in os.walk(root, followlinks=False):
        current = Path(parent)
        for name in sorted([*dirs, *files]):
            yield current / name
        dirs[:] = [
            name
            for name in sorted(dirs)
            if not lstat_entry(current / name).is_symlink
        ]

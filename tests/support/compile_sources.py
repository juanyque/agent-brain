#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def python_files(paths: list[str]) -> tuple[Path, ...]:
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_file() and path.suffix == ".py":
            files.append(path)
            continue
        if path.is_dir():
            files.extend(
                item
                for item in path.rglob("*.py")
                if "__pycache__" not in item.parts
            )
    return tuple(sorted(files))


def main(argv: list[str]) -> int:
    targets = python_files(argv or ["model/SCRIPTS", "skills", "tests"])
    for path in targets:
        compile(path.read_text(encoding="utf-8"), path.as_posix(), "exec")
    print(f"compiled {len(targets)} python files without writing bytecode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

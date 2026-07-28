#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "jsonschema>=4.25,<5",
#     "pydantic>=2.10,<3",
#     "pyyaml>=6.0.2,<7",
#     "typer>=0.15,<1",
# ]
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly:
#      uv run select_clauses.py REQUEST.yaml OUTPUT.yaml
# 3. The request points to a project-type manifest, project data, and document.
# ──────────────────

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import override

import typer
from selection_inputs import SelectionProjectError
from selection_project import (
    build_selection,
    request_from_file,
    selection_yaml,
)


@dataclass(frozen=True, slots=True)
class _OutputExistsError(SelectionProjectError):
    path: Path

    @override
    def __str__(self) -> str:
        return f"output already exists: {self.path}"

def _select(request_path: Path, output: Path) -> None:
    if output.exists():
        raise _OutputExistsError(path=output)

    prepared = build_selection(request_from_file(request_path))
    _ = output.parent.mkdir(parents=True, exist_ok=True)
    _ = output.write_text(selection_yaml(prepared.selection), encoding="utf-8")


def main(request: Path, output: Path) -> None:
    """Select clauses described by REQUEST and write deterministic OUTPUT."""
    try:
        _select(request, output)
    except SelectionProjectError as error:
        raise typer.BadParameter(str(error)) from None
    typer.echo(f"Selection: {output}")


if __name__ == "__main__":
    _ = typer.run(main)

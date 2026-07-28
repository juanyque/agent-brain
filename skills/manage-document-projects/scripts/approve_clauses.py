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
#      uv run approve_clauses.py REVIEW.yaml OUTPUT.yaml
# 3. REVIEW contains the professional's exact version decisions.
# ──────────────────

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import override

import typer
from approval_builder import approval_yaml, build_approval
from selection_inputs import SelectionProjectError


@dataclass(frozen=True, slots=True)
class _OutputExistsError(SelectionProjectError):
    path: Path

    @override
    def __str__(self) -> str:
        return f"output already exists: {self.path}"


def _approve(request: Path, output: Path) -> None:
    if output.exists():
        raise _OutputExistsError(path=output)
    approval = build_approval(request)
    _ = output.parent.mkdir(parents=True, exist_ok=True)
    _ = output.write_text(approval_yaml(approval), encoding="utf-8")


def main(request: Path, output: Path) -> None:
    """Validate a clause review and write its immutable approval record."""
    try:
        _approve(request, output)
    except SelectionProjectError as error:
        raise typer.BadParameter(str(error)) from None
    typer.echo(f"Legal approval: {output}")


if __name__ == "__main__":
    _ = typer.run(main)

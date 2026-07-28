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
# 2. Run:
#      uv run update_approval_status.py STATUS_UPDATE.yaml OUTPUT.yaml
# 3. Sign OUTPUT.yaml before using it in a release.
# ──────────────────

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import override

import typer
from approval_ledger import ledger_yaml
from approval_ledger_builder import build_updated_ledger
from selection_inputs import SelectionProjectError


@dataclass(frozen=True, slots=True)
class _OutputExistsError(SelectionProjectError):
    path: Path

    @override
    def __str__(self) -> str:
        return f"output already exists: {self.path}"


def _update(request: Path, output: Path) -> None:
    if output.exists():
        raise _OutputExistsError(path=output)
    ledger = build_updated_ledger(request)
    _ = output.parent.mkdir(parents=True, exist_ok=True)
    _ = output.write_text(ledger_yaml(ledger), encoding="utf-8")


def main(request: Path, output: Path) -> None:
    """Write the next immutable approval-status ledger revision."""
    try:
        _update(request, output)
    except SelectionProjectError as error:
        raise typer.BadParameter(str(error)) from None
    typer.echo(f"Approval ledger: {output}")


if __name__ == "__main__":
    _ = typer.run(main)

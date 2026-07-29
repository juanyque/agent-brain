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
# 1. Install uv.
# 2. Run through setup.sh; it supplies typed configuration overrides.
# 3. For diagnostics: uv run configure_workspace.py --help
# ──────────────────

from __future__ import annotations

from typing import Annotated

import typer
from selection_inputs import SelectionProjectError
from workspace_config import configuration_yaml
from workspace_setup import configure_workspace


def main(
    apply: Annotated[bool, typer.Option("--apply")] = False,
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive"),
    ] = False,
) -> None:
    """Create or update the deterministic workspace configuration."""
    try:
        outcome = configure_workspace(apply, non_interactive)
    except SelectionProjectError as error:
        raise typer.BadParameter(str(error)) from None
    if not apply:
        typer.echo(f"PLAN    configuration {outcome.path}")
        typer.echo(configuration_yaml(outcome.configuration))
    else:
        status = "WRITE" if outcome.changed else "SKIP "
        typer.echo(f"{status}   configuration {outcome.path}")
    typer.echo(
        "OPTIONAL_TOOLS "
        f"weasyprint={outcome.configuration.optional_tools.weasyprint.value} "
        f"libreoffice={outcome.configuration.optional_tools.libreoffice.value} "
        f"openssh={outcome.configuration.optional_tools.openssh.value}",
    )


if __name__ == "__main__":
    _ = typer.run(main)

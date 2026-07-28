#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "typer>=0.15,<1",
# ]
# ///

from __future__ import annotations

from pathlib import Path

import typer

_OVERRIDE_CONTENT = "data: {}\n"


def main(project: Path, apply: bool = False) -> None:
    target = project / "data" / "defaults.override.yaml"
    if target.exists():
        typer.echo(f"unchanged: {target}")
        return
    if not apply:
        typer.echo(f"would create: {target}")
        return
    _ = target.parent.mkdir(parents=True, exist_ok=True)
    _ = target.write_text(_OVERRIDE_CONTENT, encoding="utf-8")
    typer.echo(f"created: {target}")


if __name__ == "__main__":
    _ = typer.run(main)

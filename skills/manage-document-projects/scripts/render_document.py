#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "jinja2>=3.1.6,<4",
#     "jsonschema>=4.25,<5",
#     "pydantic>=2.10,<3",
#     "pyyaml>=6.0.2,<7",
#     "typer>=0.15,<1",
# ]
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv, no pip install needed):
#      uv run render_document.py TEMPLATE.md.j2 DATA.yaml OUTPUT.pdf
# 3. Or make executable and run:
#      chmod +x render_document.py
#      ./render_document.py TEMPLATE.md.j2 DATA.yaml OUTPUT.pdf
# ──────────────────

"""Render strict Jinja Markdown templates as draft Markdown and PDF."""

from __future__ import annotations

from pathlib import Path

import typer
from document_renderer import RenderRequest, render_document
from selection_inputs import SelectionProjectError


def main(template: Path, data: Path, output: Path) -> None:
    """Render TEMPLATE with DATA into OUTPUT and a sibling Markdown file."""
    request = RenderRequest(template=template, data=data, pdf=output)
    try:
        selection = render_document(request)
    except SelectionProjectError as error:
        raise typer.BadParameter(str(error)) from None
    typer.echo(f"Markdown: {request.markdown}")
    if selection is not None:
        typer.echo(f"Selection: {selection}")
    typer.echo(f"Provenance: {request.provenance}")
    typer.echo(f"PDF: {request.pdf}")


if __name__ == "__main__":
    _ = typer.run(main)

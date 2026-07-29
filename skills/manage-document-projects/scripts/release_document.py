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
# 2. Run directly:
#      uv run release_document.py RELEASE.yaml OUTPUT.pdf
# 3. RELEASE points to signed governance, data, checks, and release date.
# ──────────────────

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, ClassVar, Literal

import typer
from document_publication import PublicationSpec
from document_renderer import RenderRequest, render_document
from pydantic import BaseModel, ConfigDict
from selection_inputs import SelectionProjectError, load_yaml, resolve
from workspace_bootstrap import ensure_workspace
from workspace_config import ResolvedWorkspace


class _ReleaseRequestFile(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    release_version: Literal["0.2.0"]
    template: Path
    data: Path
    approval: Path
    approval_signature: Path
    approval_ledger: Path
    approval_ledger_signature: Path
    allowed_signers: Path
    jurisdiction_checks: Path
    release_date: date


def _release(
    request_path: Path,
    output: Path,
    workspace: ResolvedWorkspace,
) -> Path:
    request = load_yaml(request_path, _ReleaseRequestFile)
    base = request_path.parent
    _ = render_document(
        RenderRequest(
            template=resolve(request.template, base),
            data=resolve(request.data, base),
            pdf=output,
            workspace=workspace,
            publication=PublicationSpec(
                approval=resolve(request.approval, base),
                approval_signature=resolve(request.approval_signature, base),
                approval_ledger=resolve(request.approval_ledger, base),
                approval_ledger_signature=resolve(
                    request.approval_ledger_signature,
                    base,
                ),
                allowed_signers=resolve(request.allowed_signers, base),
                jurisdiction_checks=resolve(request.jurisdiction_checks, base),
                release_date=request.release_date,
            ),
        ),
    )
    return output.with_suffix(".selection.yaml")


def main(
    request: Path,
    output: Path,
    profile: Annotated[
        str | None,
        typer.Option("--profile"),
    ] = None,
) -> None:
    """Publish a reviewed document described by RELEASE into OUTPUT."""
    try:
        selection = _release(request, output, ensure_workspace(profile))
    except SelectionProjectError as error:
        raise typer.BadParameter(str(error)) from None
    typer.echo(f"Markdown: {output.with_suffix('.md')}")
    typer.echo(f"Selection: {selection}")
    typer.echo(f"Provenance: {output.with_suffix('.provenance.yaml')}")
    typer.echo(f"PDF: {output}")


if __name__ == "__main__":
    _ = typer.run(main)

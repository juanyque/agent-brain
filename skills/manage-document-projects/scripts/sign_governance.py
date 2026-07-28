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
#      uv run sign_governance.py ARTIFACT PRIVATE_KEY SIGNATURE
# 3. Keep the private key outside the document project.
# ──────────────────

from __future__ import annotations

from pathlib import Path

import typer
from artifact_authenticity import sign_artifact


def main(artifact: Path, private_key: Path, signature: Path) -> None:
    """Sign exact governance bytes without modifying the source artifact."""
    if signature.exists():
        raise typer.BadParameter(f"output already exists: {signature}")
    _ = signature.parent.mkdir(parents=True, exist_ok=True)
    _ = signature.write_bytes(sign_artifact(artifact, private_key))
    typer.echo(f"Signature: {signature}")


if __name__ == "__main__":
    _ = typer.run(main)

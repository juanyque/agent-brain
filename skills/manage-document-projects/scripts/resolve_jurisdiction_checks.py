#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "httpx2[http2,brotli,zstd]>=2.9,<3",
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
#      uv run resolve_jurisdiction_checks.py REQUEST.yaml OUTPUT.yaml
# 3. REQUEST records operator outcomes and their declared official sources.
# ──────────────────

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Final, override

import httpx2
import typer
from jurisdiction_resolver import resolution_yaml, resolve_checks
from selection_inputs import SelectionProjectError

_LIMITS: Final = httpx2.Limits(
    max_connections=200,
    max_keepalive_connections=40,
    keepalive_expiry=30.0,
)
_TIMEOUT: Final = httpx2.Timeout(
    connect=5.0,
    read=30.0,
    write=10.0,
    pool=10.0,
)
_SOCKET_OPTIONS: Final = [
    (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
]


@dataclass(frozen=True, slots=True)
class _OutputExistsError(SelectionProjectError):
    path: Path

    @override
    def __str__(self) -> str:
        return f"output already exists: {self.path}"


def _raise_on_error(response: httpx2.Response) -> None:
    response.raise_for_status()


def _resolve(request: Path, output: Path) -> None:
    if output.exists():
        raise _OutputExistsError(path=output)
    transport = httpx2.HTTPTransport(
        http2=True,
        retries=3,
        limits=_LIMITS,
        socket_options=_SOCKET_OPTIONS,
    )
    try:
        with httpx2.Client(
            transport=transport,
            timeout=_TIMEOUT,
            follow_redirects=True,
            event_hooks={"response": [_raise_on_error]},
        ) as client:
            resolution = resolve_checks(request, client)
    except httpx2.HTTPError as error:
        raise typer.BadParameter(str(error)) from None
    _ = output.parent.mkdir(parents=True, exist_ok=True)
    _ = output.write_text(resolution_yaml(resolution), encoding="utf-8")


def main(request: Path, output: Path) -> None:
    """Resolve jurisdiction checks and write their official evidence."""
    try:
        _resolve(request, output)
    except SelectionProjectError as error:
        raise typer.BadParameter(str(error)) from None
    typer.echo(f"Jurisdiction checks: {output}")


if __name__ == "__main__":
    _ = typer.run(main)

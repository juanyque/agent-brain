"""Shared helpers for obsidian skill runtime scripts.

Internal module (leading underscore) — not intended to be invoked directly.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path


class Reporter:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.lines: list[str] = []

    def write(self, line: str = "") -> None:
        print(line)
        self.lines.append(line)

    def flush(self) -> None:
        self.log_path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def build_command_string() -> str:
    """Return the current invocation as a shell-safe quoted string."""
    return " ".join(shlex.quote(part) for part in sys.argv)

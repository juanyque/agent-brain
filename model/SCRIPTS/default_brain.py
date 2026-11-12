#!/usr/bin/env python3
"""Per-machine default brain, used when a session starts outside every brain.

The default is an explicit user choice stored OUTSIDE any repository, so each
machine can have its own:

    ${XDG_CONFIG_HOME:-~/.config}/agent-brain/default_brain.json
    {"version": 1, "brain": "/absolute/path/to/brain"}

Reading is always safe: any problem (missing file, malformed JSON, unsupported
version, removed or unmounted brain, brain implanted with another model) is
reported as "no usable default" and nothing is cleaned up on disk.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from brain_state import current_brain_status

CONFIG_DIR_NAME = "agent-brain"
CONFIG_FILE_NAME = "default_brain.json"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DefaultBrain:
    """Outcome of reading the default.

    status is one of: unset, invalid, ok. `brain` is set only when status is ok.
    """

    status: str
    brain: Path | None = None
    reason: str | None = None


def config_path() -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    if configured and Path(configured).is_absolute():
        base = Path(configured)
    else:
        base = Path.home() / ".config"
    return base / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def read_default() -> DefaultBrain:
    path = config_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DefaultBrain("unset")
    except OSError as exc:
        return DefaultBrain("invalid", reason=f"cannot read {path}: {exc.strerror or exc}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return DefaultBrain("invalid", reason=f"{path} is not valid JSON")
    if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
        return DefaultBrain("invalid", reason=f"{path} has an unsupported schema")
    brain_value = data.get("brain")
    if not isinstance(brain_value, str) or not Path(brain_value).is_absolute():
        return DefaultBrain("invalid", reason="default brain must be an absolute path")
    brain = Path(brain_value)
    if not brain.is_dir():
        return DefaultBrain("invalid", reason=f"default brain does not exist: {brain}")
    status = current_brain_status(brain)
    if status != "ok":
        return DefaultBrain("invalid", reason=f"default brain is not a current-model brain ({status})")
    return DefaultBrain("ok", brain=brain.resolve())


def validate_brain(brain: Path) -> str | None:
    """Return None when `brain` can be a default, otherwise the reason it cannot."""
    if not brain.is_dir():
        return f"not a directory: {brain}"
    status = current_brain_status(brain)
    if status != "ok":
        return f"not a current-model brain ({status}): {brain}"
    return None


def write_default(brain: Path) -> Path:
    """Atomically store `brain` as the default. Caller must validate it first."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps({"version": SCHEMA_VERSION, "brain": str(brain.resolve())}) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".default_brain.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    return path


def clear_default() -> bool:
    """Remove the default. Returns True when a file was removed."""
    try:
        config_path().unlink()
    except FileNotFoundError:
        return False
    return True

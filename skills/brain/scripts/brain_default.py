#!/usr/bin/env python3
"""Show, set or clear this machine's default brain.

The default is only used when a session starts outside every brain (for
example in a git worktree under /tmp). It lives outside any repository
(${XDG_CONFIG_HOME:-~/.config}/agent-brain/default_brain.json), so each
machine keeps its own.

Usage:
    python3 brain_default.py get
    python3 brain_default.py set --brain-root PATH            # dry-run
    python3 brain_default.py set --brain-root PATH --apply
    python3 brain_default.py clear [--apply]

Exit codes:
    0 - get found a usable default; set/clear succeeded (or dry-run would)
    1 - get found no usable default (unset or invalid)
    2 - set was given a path that cannot be a default
Output is JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_SCRIPTS = REPO_ROOT / "model" / "SCRIPTS"
if str(MODEL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MODEL_SCRIPTS))

import default_brain  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("get", help="Show the default brain and whether it is usable.")
    set_cmd = sub.add_parser("set", help="Choose the default brain.")
    set_cmd.add_argument("--brain-root", required=True)
    set_cmd.add_argument("--apply", action="store_true", help="Write the default (otherwise dry-run).")
    clear_cmd = sub.add_parser("clear", help="Remove the default.")
    clear_cmd.add_argument("--apply", action="store_true", help="Remove it (otherwise dry-run).")
    return parser.parse_args()


def emit(payload: dict) -> None:
    print(json.dumps(payload))


def main() -> int:
    args = parse_args()
    path = default_brain.config_path()

    if args.command == "get":
        current = default_brain.read_default()
        payload = {"config": str(path), "status": current.status}
        if current.brain is not None:
            payload["brain"] = str(current.brain)
        if current.reason:
            payload["reason"] = current.reason
        emit(payload)
        return 0 if current.status == "ok" else 1

    if args.command == "set":
        brain = Path(args.brain_root).expanduser().resolve()
        problem = default_brain.validate_brain(brain)
        if problem:
            emit({"config": str(path), "status": "refused", "reason": problem})
            return 2
        if not args.apply:
            emit({"config": str(path), "status": "dry-run", "brain": str(brain)})
            return 0
        default_brain.write_default(brain)
        emit({"config": str(path), "status": "set", "brain": str(brain)})
        return 0

    exists = path.exists()
    if args.apply:
        default_brain.clear_default()
        emit({"config": str(path), "status": "cleared" if exists else "unset"})
    else:
        emit({"config": str(path), "status": "dry-run", "would_remove": exists})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

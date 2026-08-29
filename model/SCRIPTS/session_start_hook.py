#!/usr/bin/env python3
"""Portable SessionStart hook: reminds the agent to connect the brain when a
session starts inside one, for any runtime (Claude Code, Codex, ...).

Unlike a per-installation hook that hardcodes one brain's absolute path, this
script discovers the active brain dynamically from the hook's own `cwd`, via
`find_home.py` -- the same discovery the brain skill's own session-start
protocol uses. One script, shipped once with the model, works unmodified for
any brain and any cwd inside it, including a person with more than one brain.

Usage (wired into the runtime's own hook config, one entry per runtime):
    python3 session_start_hook.py --runtime claude
    python3 session_start_hook.py --runtime codex

stdin: the runtime's own SessionStart hook payload (JSON). Only `cwd` is used;
its absence or a malformed payload is not an error -- see resolve_cwd().

stdout: the runtime's own SessionStart hook response contract. Both Claude
Code and Codex share the same shape (verified empirically against Codex CLI
0.150.1: hookSpecificOutput.additionalContext is genuinely injected into the
agent's own turn, not just schema-accepted-but-ignored) --
`{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}`
when a brain is found, `{}` otherwise. A future runtime with a different
contract gets its own branch in RUNTIME_MESSAGES plus (if the response shape
itself differs) a conditional in main(), not a second copy of this script.

Fails safe: any error here (missing find_home.py, a brain-less cwd, a
subprocess timeout, malformed JSON) must never break session start for the
user -- every path that isn't "yes, inject the instruction" prints an empty
JSON object and exits 0.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# The exact invocation phrase differs per runtime (confirmed empirically,
# 2026-08-29): Claude Code's registered `/brain` slash command reliably runs
# the session-start protocol from a plain "invoke the brain skill" reminder.
# Codex's `$brain` is plain chat text the agent has to interpret, not a
# registered command -- leaving off the explicit "nueva sesion en español"
# argument produced unreliable initialization and the wrong response
# language, so that runtime's phrasing spells out the exact invocation.
RUNTIME_MESSAGES = {
    "claude": (
        "This session started inside the {name} brain vault. Before "
        "anything else, invoke the `brain` skill to connect this session "
        "(new or resumed) per its own logic -- do not wait for the user to "
        "say \"nueva sesión\" or similar."
    ),
    "codex": (
        "This session started inside the {name} brain vault. Before "
        "anything else, run `$brain nueva sesion en español` to connect "
        "this session (new or resumed) per its own logic -- do not wait "
        "for the user to ask for it."
    ),
}


def resolve_cwd(hook_input: object) -> str:
    cwd = hook_input.get("cwd") if isinstance(hook_input, dict) else None
    if isinstance(cwd, str) and cwd:
        return cwd
    return os.environ.get("PWD") or os.getcwd()


def resolve_agent_brain_home() -> Path:
    configured = os.environ.get("AGENT_BRAIN_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "share" / "agent-brain"


def find_brain(cwd: str, agent_brain_home: Path) -> dict | None:
    """Return the nearest implanted brain's find_home.py record for `cwd`, or
    None if none is found or discovery itself fails for any reason.
    """
    find_home = agent_brain_home / "skills" / "brain" / "scripts" / "find_home.py"
    if not find_home.is_file():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(find_home), cwd],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    homes = payload.get("homes") if isinstance(payload, dict) else None
    if not homes or not isinstance(homes, list):
        return None
    first = homes[0]
    return first if isinstance(first, dict) else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Portable brain-connect SessionStart hook.")
    parser.add_argument("--runtime", required=True, choices=sorted(RUNTIME_MESSAGES))
    args = parser.parse_args()

    try:
        raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        hook_input = {}

    cwd = resolve_cwd(hook_input)
    brain = find_brain(cwd, resolve_agent_brain_home())
    if brain is None:
        print("{}")
        return 0

    name = brain.get("name") or "connected"
    message = RUNTIME_MESSAGES[args.runtime].format(name=name)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": message,
        }
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print("{}")
        sys.exit(0)

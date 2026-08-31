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
    python3 session_start_hook.py --runtime opencode

stdin: the runtime's own SessionStart hook payload (JSON). Only `cwd` is used;
its absence or a malformed payload is not an error -- see resolve_cwd().

stdout: the runtime's own SessionStart hook response contract. Claude Code,
Codex, and the OpenCode bridge share the same shape (verified empirically against Codex CLI
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
from typing import TypeAlias

# The exact invocation phrase differs per runtime (confirmed empirically,
# 2026-08-29): Claude Code's registered `/brain` slash command reliably runs
# the session-start protocol from a plain "invoke the brain skill" reminder.
# In Codex and OpenCode, `$brain` is plain chat text the agent has to interpret, not a
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
    "opencode": (
        "This session started inside the {name} brain vault. Before "
        "anything else, run `$brain nueva sesion en español` to connect "
        "this session (new or resumed) per its own logic -- do not wait "
        "for the user to ask for it."
    ),
}

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class InvalidHookPayloadError(ValueError):
    pass


def resolve_cwd(hook_input: JsonValue) -> str:
    cwd = hook_input.get("cwd") if isinstance(hook_input, dict) else None
    if isinstance(cwd, str) and cwd:
        return cwd
    return os.environ.get("PWD") or os.getcwd()


def resolve_agent_brain_home() -> Path:
    configured = os.environ.get("AGENT_BRAIN_HOME")
    if configured:
        return Path(configured).expanduser()
    # The hook is always invoked via its own installed absolute path
    # (model/SCRIPTS/session_start_hook.py), so that path IS the checkout --
    # no env var needed for the common case, and no risk of guessing a
    # different, stale checkout when AGENT_BRAIN_HOME isn't exported.
    return Path(__file__).resolve().parents[2]


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
    try:
        args = parser.parse_args()
    except SystemExit:
        # A misconfigured hook entry (missing/misspelled --runtime) is still
        # a fail-safe case, not just runtime-discovery errors: a bad CLI
        # invocation must not surface as a crashing hook on every session.
        print("{}")
        return 0

    try:
        raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
        if not isinstance(hook_input, dict):
            # `[]`, `null`, and a bare scalar are all syntactically valid
            # JSON but not a usable hook payload -- treat the same as a
            # parse failure, not a payload resolve_cwd() should inspect.
            raise InvalidHookPayloadError("hook payload must be a JSON object")
    except (InvalidHookPayloadError, json.JSONDecodeError, OSError):
        # Fail closed immediately -- do not fall through to a PWD-based cwd
        # guess, which could still find a real brain and inject the
        # reminder despite the malformed input.
        print("{}")
        return 0

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
    except Exception:  # noqa: BROAD_EXCEPT_OK
        print("{}")
        sys.exit(0)

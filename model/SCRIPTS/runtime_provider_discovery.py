#!/usr/bin/env python3
"""Read-only MCP registry discovery for supported agent runtimes.

Discovery never returns command lines, URLs, environment variables, headers, or
raw runtime output. It exposes only server names and normalized readiness.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class McpServerStatus:
    name: str
    state: str
    detail: str


@dataclass(frozen=True)
class RuntimeDiscovery:
    runtime: str
    state: str
    detail: str
    servers: dict[str, McpServerStatus]


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


def _discover_codex(runner: Runner) -> RuntimeDiscovery:
    result = runner(["codex", "mcp", "list", "--json"])
    if result.returncode != 0:
        return RuntimeDiscovery("codex", "error", "registry command failed", {})
    try:
        records = json.loads(result.stdout)
    except json.JSONDecodeError:
        return RuntimeDiscovery("codex", "error", "registry returned invalid JSON", {})
    if not isinstance(records, list):
        return RuntimeDiscovery("codex", "error", "registry returned an unexpected shape", {})

    servers: dict[str, McpServerStatus] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("name"), str):
            continue
        name = record["name"]
        enabled = record.get("enabled", True)
        auth_status = record.get("auth_status")
        if enabled is False:
            state = "unavailable"
            detail = "disabled in runtime registry"
        elif auth_status == "not_logged_in":
            state = "unavailable"
            detail = "authentication required"
        else:
            state = "registered"
            detail = "enabled in runtime registry; connectivity not probed"
        servers[name] = McpServerStatus(name, state, detail)
    return RuntimeDiscovery("codex", "ok", "registry inspected", servers)


def discover_mcp_servers(
    runtime: str,
    *,
    runner: Runner = _default_runner,
) -> RuntimeDiscovery:
    """Discover sanitized MCP readiness without exposing runtime configuration."""
    try:
        if runtime == "codex":
            return _discover_codex(runner)
        if runtime == "claude":
            return RuntimeDiscovery(
                runtime,
                "unsupported",
                "Claude's registry command may rewrite runtime settings; use active tool-catalog verification",
                {},
            )
        return RuntimeDiscovery(
            runtime,
            "unsupported",
            "no safe MCP discovery adapter is implemented",
            {},
        )
    except FileNotFoundError:
        return RuntimeDiscovery(runtime, "unavailable", "runtime command not found", {})
    except subprocess.TimeoutExpired:
        return RuntimeDiscovery(runtime, "error", "registry command timed out", {})

#!/usr/bin/env python3
"""Resolve environment-profile capabilities into sanitized runtime context."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "model" / "SCRIPTS"
sys.path.insert(0, str(SCRIPTS_DIR))

from environment_profiles import (  # noqa: E402
    ProfileError,
    capability_tool_exposure,
    provider_statuses,
    resolve_capability,
    resolve_profile,
)
from runtime_provider_discovery import discover_mcp_servers  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve generic capabilities through an environment profile"
    )
    parser.add_argument("--brain-root", required=True)
    parser.add_argument("--capability", action="append", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--cwd", default=str(Path.cwd()))
    parser.add_argument(
        "--runtime",
        choices=("claude", "codex", "opencode", "generic"),
        default="generic",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Inspect the selected runtime's MCP registry before resolving",
    )
    parser.add_argument(
        "--include-policy",
        action="store_true",
        help="Include the selected profile's issue-tracking policy",
    )
    parser.add_argument(
        "--available-tool",
        action="append",
        default=[],
        help="Exact tool name exposed in the active agent catalog",
    )
    parser.add_argument(
        "--tool-catalog-complete",
        action="store_true",
        help="Treat omitted MCP invocation names as unavailable",
    )
    args = parser.parse_args()

    try:
        resolved = resolve_profile(
            Path(args.brain_root).expanduser().resolve(),
            explicit_profile=args.profile,
            cwd=Path(args.cwd).expanduser(),
        )
        discovery = discover_mcp_servers(args.runtime) if args.live else None
        if discovery and discovery.state not in {"ok"}:
            raise ProfileError(
                f"{args.runtime} provider discovery failed: {discovery.detail}"
            )
        statuses = provider_statuses(
            resolved.document,
            mcp_servers=discovery.servers if discovery else None,
        )
        resolutions = [
            resolve_capability(
                resolved,
                capability,
                statuses=statuses,
                runtime=args.runtime,
            )
            for capability in args.capability
        ]
        exposure = capability_tool_exposure(
            resolutions,
            available_tools=set(args.available_tool),
            catalog_complete=args.tool_catalog_complete,
        )
        missing = [item for item in exposure if item.state == "missing"]
        if missing:
            invocations = ", ".join(
                item.invocation or item.capability for item in missing
            )
            raise ProfileError(
                "complete active tool catalog does not expose: " + invocations
            )
        capabilities = [asdict(resolution) for resolution in resolutions]
    except ProfileError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    output = {
        "ok": True,
        "profile": {
            "id": resolved.profile_id,
            "source": resolved.source,
        },
        "runtime": args.runtime,
        "live_discovery": (
            {
                "state": discovery.state,
                "detail": discovery.detail,
            }
            if discovery
            else None
        ),
        "capabilities": capabilities,
        "tool_exposure": [asdict(item) for item in exposure],
    }
    if args.include_policy:
        output["issue_tracking"] = resolved.document.get("issue_tracking")
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

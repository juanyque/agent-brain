#!/usr/bin/env python3
"""Preflight profile secret references without resolving secret values."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Collection
from pathlib import Path

from _common import Reporter, build_command_string
from environment_profiles import ProfileError, resolve_profile, secret_statuses


SecretCheck = Callable[[str], tuple[str, str]]


def macos_keychain_check(
    name: str,
    *,
    platform: str = sys.platform,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, str]:
    """Check keychain item metadata while discarding all command output."""
    if platform != "darwin":
        return "adapter-check", f"keychain reference {name} requires a platform adapter"
    try:
        result = runner(
            ["security", "find-generic-password", "-s", name],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            text=True,
        )
    except FileNotFoundError:
        return "unavailable", "macOS keychain command is unavailable"
    except subprocess.TimeoutExpired:
        return "unavailable", "macOS keychain metadata check timed out"
    if result.returncode == 0:
        return "available", f"keychain reference {name}"
    if result.returncode == 44:
        return "missing", f"keychain reference {name}"
    return "unavailable", f"keychain metadata check failed for reference {name}"


def runtime_catalog_check(
    available_names: Collection[str],
    *,
    complete: bool,
) -> SecretCheck:
    available = frozenset(available_names)

    def check(name: str) -> tuple[str, str]:
        if name in available:
            return "available", f"runtime-native reference {name}"
        if complete:
            return "missing", f"runtime-native reference {name}"
        return "adapter-check", f"runtime-native reference {name} requires a complete catalog"

    return check


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check profile secret references without reading secret values"
    )
    parser.add_argument("--brain", required=True, help="Path to the brain root")
    parser.add_argument("--profile", help="Explicit profile id")
    parser.add_argument("--cwd", help="Working directory used for profile selection")
    parser.add_argument(
        "--keychain",
        choices=("none", "macos"),
        default="none",
        help="Optional metadata-only keychain adapter",
    )
    parser.add_argument(
        "--runtime-secret",
        action="append",
        default=[],
        help="Runtime-native secret name reported available by the active adapter",
    )
    parser.add_argument(
        "--runtime-catalog-complete",
        action="store_true",
        help="Treat omitted runtime-native names as missing instead of unresolved",
    )
    args = parser.parse_args()

    reporter = Reporter(Path(__file__).with_suffix(".log"))
    try:
        brain = Path(args.brain).expanduser().resolve()
        if not brain.is_dir():
            raise ProfileError(f"brain directory not found: {brain}")
        resolved = resolve_profile(
            brain,
            explicit_profile=args.profile,
            cwd=Path(args.cwd).expanduser() if args.cwd else None,
        )
        keychain_check = macos_keychain_check if args.keychain == "macos" else None
        runtime_check = runtime_catalog_check(
            args.runtime_secret,
            complete=args.runtime_catalog_complete,
        )
        statuses = secret_statuses(
            resolved.document,
            keychain_check=keychain_check,
            runtime_secret_check=runtime_check,
        )

        reporter.write("# Profile secret preflight")
        reporter.write(f"command: {build_command_string()}")
        reporter.write(f"profile: {resolved.profile_id} ({resolved.source})")
        if not statuses:
            reporter.write("secret references: none")
        for status in statuses:
            requirement = "required" if status.required else "optional"
            reporter.write(
                f"  {status.state.upper():13} {status.provider_id}: "
                f"{status.kind}/{status.name} ({requirement})"
            )
        unresolved_required = [
            status
            for status in statuses
            if status.required and status.state != "available"
        ]
        if unresolved_required:
            reporter.write("Preflight failed: required secret references are not available.")
            reporter.flush()
            return 1
        reporter.write("Secret preflight completed without resolving values.")
        reporter.flush()
        return 0
    except (OSError, ProfileError) as exc:
        reporter.write(f"ERROR: {exc}")
        reporter.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

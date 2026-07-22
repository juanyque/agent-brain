from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "model" / "SCRIPTS"
sys.path.insert(0, str(SCRIPTS_DIR))

from runtime_provider_discovery import discover_mcp_servers  # noqa: E402


def completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="redacted")


class RuntimeProviderDiscoveryTests(unittest.TestCase):
    def test_codex_normalizes_registry_without_transport_details(self) -> None:
        records = [
            {"name": "ready", "enabled": True, "auth_status": "unsupported", "url": "secret"},
            {"name": "login", "enabled": True, "auth_status": "not_logged_in"},
            {"name": "off", "enabled": False, "auth_status": "unsupported"},
        ]
        discovery = discover_mcp_servers(
            "codex",
            runner=lambda command: completed(json.dumps(records)),
        )
        self.assertEqual(discovery.state, "ok")
        self.assertEqual(discovery.servers["ready"].state, "registered")
        self.assertEqual(discovery.servers["login"].state, "unavailable")
        self.assertEqual(discovery.servers["off"].state, "unavailable")
        self.assertNotIn("secret", repr(discovery))

    def test_claude_discovery_refuses_stateful_registry_command(self) -> None:
        called = False

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            nonlocal called
            called = True
            return completed("sensitive output")

        discovery = discover_mcp_servers("claude", runner=runner)
        self.assertEqual(discovery.state, "unsupported")
        self.assertIn("may rewrite runtime settings", discovery.detail)
        self.assertFalse(called)

    def test_unsupported_runtime_is_explicit(self) -> None:
        discovery = discover_mcp_servers("opencode")
        self.assertEqual(discovery.state, "unsupported")
        self.assertEqual(discovery.servers, {})


if __name__ == "__main__":
    unittest.main()

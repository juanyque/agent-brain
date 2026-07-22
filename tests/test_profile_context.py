from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "brain" / "scripts" / "profile_context.py"


class ProfileContextCliTests(unittest.TestCase):
    def test_resolves_sanitized_capability_context(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "brain"
            shared = brain / "_AGENTS" / "SHARED"
            profiles = shared / "profiles"
            profiles.mkdir(parents=True)
            shutil.copy(
                ROOT / "examples" / "profiles" / "environment.json",
                shared / "environment.json",
            )
            shutil.copy(
                ROOT / "examples" / "profiles" / "work.json",
                profiles / "work.json",
            )
            shutil.copytree(
                ROOT / "examples" / "profiles" / "work",
                profiles / "work",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--brain-root",
                    str(brain),
                    "--capability",
                    "issues.create",
                    "--runtime",
                    "codex",
                    "--available-tool",
                    "mcp__work_tracker__createIssue",
                    "--tool-catalog-complete",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertTrue(output["ok"])
            self.assertEqual(output["profile"]["id"], "work")
            self.assertEqual(
                output["capabilities"][0]["invocation"],
                "mcp__work_tracker__createIssue",
            )
            self.assertEqual(output["tool_exposure"][0]["state"], "available")

    def test_complete_active_catalog_fails_when_exact_tool_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "brain"
            shared = brain / "_AGENTS" / "SHARED"
            profiles = shared / "profiles"
            profiles.mkdir(parents=True)
            shutil.copy(
                ROOT / "examples" / "profiles" / "environment.json",
                shared / "environment.json",
            )
            shutil.copy(
                ROOT / "examples" / "profiles" / "work.json",
                profiles / "work.json",
            )
            shutil.copytree(
                ROOT / "examples" / "profiles" / "work",
                profiles / "work",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--brain-root",
                    str(brain),
                    "--capability",
                    "issues.create",
                    "--runtime",
                    "codex",
                    "--tool-catalog-complete",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            output = json.loads(result.stdout)
            self.assertFalse(output["ok"])
            self.assertIn("does not expose", output["error"])

    def test_incomplete_catalog_never_claims_missing_tool_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "brain"
            shared = brain / "_AGENTS" / "SHARED"
            profiles = shared / "profiles"
            profiles.mkdir(parents=True)
            shutil.copy(
                ROOT / "examples" / "profiles" / "environment.json",
                shared / "environment.json",
            )
            shutil.copy(
                ROOT / "examples" / "profiles" / "work.json",
                profiles / "work.json",
            )
            shutil.copytree(
                ROOT / "examples" / "profiles" / "work",
                profiles / "work",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--brain-root",
                    str(brain),
                    "--capability",
                    "issues.create",
                    "--runtime",
                    "codex",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["tool_exposure"][0]["state"], "unverified")


if __name__ == "__main__":
    unittest.main()

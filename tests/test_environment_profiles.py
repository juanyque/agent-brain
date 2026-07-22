from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "model" / "SCRIPTS"
sys.path.insert(0, str(SCRIPTS_DIR))

from environment_profiles import (  # noqa: E402
    PROFILE_ENV,
    ProfileError,
    load_profile_documents,
    provider_statuses,
    resolve_capability,
    resolve_profile,
)
from runtime_provider_discovery import McpServerStatus  # noqa: E402


class EnvironmentProfileTests(unittest.TestCase):
    def make_brain(self, root: Path) -> Path:
        brain = root / "brain"
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
        return brain

    def test_loads_and_resolves_default_profile(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = self.make_brain(Path(raw))
            resolved = resolve_profile(brain, cwd=Path(raw) / "unmatched", environ={})
            self.assertEqual(resolved.profile_id, "work")
            self.assertEqual(resolved.source, "default_profile")

    def test_explicit_profile_precedes_environment(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = self.make_brain(Path(raw))
            resolved = resolve_profile(
                brain,
                explicit_profile="work",
                environ={PROFILE_ENV: "missing"},
            )
            self.assertEqual(resolved.profile_id, "work")
            self.assertEqual(resolved.source, "explicit --profile")

    def test_longest_project_prefix_wins(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = self.make_brain(root)
            selection_path = brain / "_AGENTS" / "SHARED" / "environment.json"
            selection = json.loads(selection_path.read_text(encoding="utf-8"))
            selection["project_rules"] = [
                {"path_prefix": str(root / "work"), "profile": "work"},
                {"path_prefix": str(root / "work" / "nested"), "profile": "work"},
            ]
            selection_path.write_text(json.dumps(selection), encoding="utf-8")

            resolved = resolve_profile(
                brain,
                cwd=root / "work" / "nested" / "project",
                environ={},
            )
            self.assertEqual(
                resolved.source,
                f"project rule {root / 'work' / 'nested'}",
            )

    def test_rejects_unknown_fields_and_broken_routes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = self.make_brain(Path(raw))
            profile_path = brain / "_AGENTS" / "SHARED" / "profiles" / "work.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["unexpected"] = True
            profile["capability_routes"]["issues.read"] = ["missing"]
            profile_path.write_text(json.dumps(profile), encoding="utf-8")

            with self.assertRaises(ProfileError) as raised:
                load_profile_documents(brain)
            message = str(raised.exception)
            self.assertIn("$.unexpected: unknown property", message)
            self.assertIn("unknown provider 'missing'", message)

    def test_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = self.make_brain(Path(raw))
            selection_path = brain / "_AGENTS" / "SHARED" / "environment.json"
            selection_path.write_text(
                '{"schema_version":1,"schema_version":1,"default_profile":"work","project_rules":[]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ProfileError, "duplicate JSON key"):
                load_profile_documents(brain)

    def test_provider_status_does_not_claim_mcp_availability(self) -> None:
        profile = json.loads(
            (ROOT / "examples" / "profiles" / "work.json").read_text(
                encoding="utf-8"
            )
        )
        statuses = {
            status.provider_id: status for status in provider_statuses(profile)
        }
        self.assertEqual(statuses["work-tracker"].state, "adapter-check")
        self.assertIn("runtime adapter", statuses["work-tracker"].detail)

    def test_capability_resolution_uses_runtime_invocation_hint(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = self.make_brain(Path(raw))
            resolved = resolve_profile(brain, environ={})
            capability = resolve_capability(
                resolved,
                "issues.create",
                runtime="codex",
            )
            self.assertEqual(capability.provider_id, "work-tracker")
            self.assertEqual(
                capability.invocation,
                "mcp__work_tracker__createIssue",
            )

    def test_unavailable_mcp_falls_through_to_manual(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = self.make_brain(Path(raw))
            resolved = resolve_profile(brain, environ={})
            statuses = provider_statuses(resolved.document, mcp_servers={})
            capability = resolve_capability(
                resolved,
                "issues.read",
                statuses=statuses,
            )
            self.assertEqual(capability.provider_id, "manual")
            with self.assertRaisesRegex(ProfileError, "no usable provider"):
                resolve_capability(
                    resolved,
                    "issues.create",
                    statuses=statuses,
                )

    def test_registered_mcp_is_selectable_but_not_claimed_available(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = self.make_brain(Path(raw))
            resolved = resolve_profile(brain, environ={})
            statuses = provider_statuses(
                resolved.document,
                mcp_servers={
                    "work-tracker": McpServerStatus(
                        "work-tracker",
                        "registered",
                        "connectivity not probed",
                    )
                },
            )
            capability = resolve_capability(
                resolved,
                "issues.create",
                statuses=statuses,
            )
            self.assertEqual(capability.availability, "registered")

    def test_rejects_invalid_environment_reference_and_duplicate_secret(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = self.make_brain(Path(raw))
            profile_path = brain / "_AGENTS" / "SHARED" / "profiles" / "work.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            references = profile["providers"]["work-tracker"]["secret_refs"]
            references[0]["name"] = "INVALID-NAME"
            references.append(dict(references[1]))
            profile_path.write_text(json.dumps(profile), encoding="utf-8")

            with self.assertRaises(ProfileError) as raised:
                load_profile_documents(brain)
            message = str(raised.exception)
            self.assertIn("valid environment variable name", message)
            self.assertIn("duplicates keychain reference", message)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "model" / "SCRIPTS"
sys.path.insert(0, str(SCRIPTS_DIR))

from environment_profiles import resolve_profile, secret_statuses  # noqa: E402
from profile_overlays import apply_overlay_plan, build_overlay_plan  # noqa: E402


def tree_snapshot(root: Path) -> list[tuple[str, str, str]]:
    snapshot: list[tuple[str, str, str]] = []
    if not root.exists():
        return snapshot
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            snapshot.append((str(relative), "symlink", os.readlink(path)))
        elif path.is_file():
            snapshot.append((str(relative), "file", path.read_text(encoding="utf-8")))
        elif path.is_dir():
            snapshot.append((str(relative), "dir", ""))
    return snapshot


class ProfileIntegrationTests(unittest.TestCase):
    def test_selection_preflight_projection_and_second_apply_share_one_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            brain = root / "brain"
            shared = brain / "_AGENTS" / "SHARED"
            profiles = shared / "profiles"
            profiles.mkdir(parents=True)
            home.mkdir()
            shutil.copy(ROOT / "examples" / "profiles" / "environment.json", shared)
            shutil.copy(ROOT / "examples" / "profiles" / "work.json", profiles)
            shutil.copytree(
                ROOT / "examples" / "profiles" / "work",
                profiles / "work",
            )
            cwd = home / "workspace" / "example-org" / "payments" / "demo-app"
            cwd.mkdir(parents=True)
            runtime_rules = home / ".runtime" / "rules"
            runtime_rules.mkdir(parents=True)
            local_rule = runtime_rules / "review-policy.md"
            local_rule.write_text("local policy\n", encoding="utf-8")
            secret_value = "integration-value-must-not-escape"

            with patch.dict(
                os.environ,
                {
                    "HOME": str(home),
                    "EXAMPLE_TRACKER_TOKEN": secret_value,
                },
                clear=True,
            ):
                resolved = resolve_profile(brain, cwd=cwd)
                secrets = secret_statuses(resolved.document)
                before_dry_run = tree_snapshot(root)
                first_plan = build_overlay_plan(
                    brain,
                    resolved,
                    runtime="codex",
                    target_roots={"rule": runtime_rules},
                )

                self.assertEqual(resolved.source, "project rule ~/workspace/example-org")
                self.assertEqual(first_plan[0].action, "quarantine-link")
                self.assertEqual(tree_snapshot(root), before_dry_run)
                self.assertNotIn(secret_value, repr(secrets))

                apply_overlay_plan(first_plan)
                after_first_apply = tree_snapshot(root)
                second_plan = build_overlay_plan(
                    brain,
                    resolved,
                    runtime="codex",
                    target_roots={"rule": runtime_rules},
                )
                apply_overlay_plan(second_plan)

            quarantine = (
                brain
                / "INBOX"
                / "_PROFILE_OVERLAYS"
                / "codex"
                / "work"
                / "rule"
                / "review-policy.md"
            )
            self.assertEqual(second_plan[0].action, "unchanged")
            self.assertEqual(tree_snapshot(root), after_first_apply)
            self.assertEqual(quarantine.read_text(encoding="utf-8"), "local policy\n")
            self.assertTrue(local_rule.is_symlink())


if __name__ == "__main__":
    unittest.main()

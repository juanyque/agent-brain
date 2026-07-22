from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "model" / "SCRIPTS"
sys.path.insert(0, str(SCRIPTS_DIR))

from environment_profiles import ProfileError, resolve_profile  # noqa: E402
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


class ProfileOverlayTests(unittest.TestCase):
    def make_brain(self, root: Path) -> Path:
        brain = root / "brain"
        shared = brain / "_AGENTS" / "SHARED"
        profiles = shared / "profiles"
        profiles.mkdir(parents=True)
        shutil.copy(ROOT / "examples" / "profiles" / "environment.json", shared)
        shutil.copy(ROOT / "examples" / "profiles" / "work.json", profiles)
        shutil.copytree(
            ROOT / "examples" / "profiles" / "work",
            profiles / "work",
        )
        return brain

    def test_dry_run_plan_does_not_mutate_runtime_or_brain(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = self.make_brain(root)
            runtime_rules = root / "runtime" / "rules"
            resolved = resolve_profile(brain, environ={})
            before = tree_snapshot(root)

            plans = build_overlay_plan(
                brain,
                resolved,
                runtime="codex",
                target_roots={"rule": runtime_rules},
            )

            self.assertEqual([plan.action for plan in plans], ["link"])
            self.assertEqual(tree_snapshot(root), before)

    def test_apply_is_idempotent_and_links_selected_resource(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = self.make_brain(root)
            runtime_rules = root / "runtime" / "rules"
            resolved = resolve_profile(brain, environ={})

            first = build_overlay_plan(
                brain,
                resolved,
                runtime="codex",
                target_roots={"rule": runtime_rules},
            )
            apply_overlay_plan(first)
            target = runtime_rules / "review-policy.md"
            after_first = tree_snapshot(root)
            second = build_overlay_plan(
                brain,
                resolved,
                runtime="codex",
                target_roots={"rule": runtime_rules},
            )
            apply_overlay_plan(second)

            self.assertTrue(target.is_symlink())
            self.assertEqual(second[0].action, "unchanged")
            self.assertEqual(tree_snapshot(root), after_first)

    def test_conflict_is_quarantined_once_before_linking(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = self.make_brain(root)
            runtime_rules = root / "runtime" / "rules"
            runtime_rules.mkdir(parents=True)
            target = runtime_rules / "review-policy.md"
            target.write_text("local rule\n", encoding="utf-8")
            resolved = resolve_profile(brain, environ={})

            plans = build_overlay_plan(
                brain,
                resolved,
                runtime="codex",
                target_roots={"rule": runtime_rules},
            )
            apply_overlay_plan(plans)
            quarantine = (
                brain
                / "INBOX"
                / "_PROFILE_OVERLAYS"
                / "codex"
                / "work"
                / "rule"
                / "review-policy.md"
            )
            after_first = tree_snapshot(root)
            second = build_overlay_plan(
                brain,
                resolved,
                runtime="codex",
                target_roots={"rule": runtime_rules},
            )
            apply_overlay_plan(second)

            self.assertEqual(plans[0].action, "quarantine-link")
            self.assertEqual(quarantine.read_text(encoding="utf-8"), "local rule\n")
            self.assertTrue(target.is_symlink())
            self.assertEqual(tree_snapshot(root), after_first)

    def test_missing_target_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = self.make_brain(root)
            resolved = resolve_profile(brain, environ={})

            with self.assertRaisesRegex(ProfileError, "missing --target-root"):
                build_overlay_plan(
                    brain,
                    resolved,
                    runtime="codex",
                    target_roots={},
                )

    def test_unsafe_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = self.make_brain(root)
            profile_path = brain / "_AGENTS" / "SHARED" / "profiles" / "work.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["runtime_overlays"][0]["target"] = "../outside.md"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")

            with self.assertRaises(ProfileError) as raised:
                resolve_profile(brain, environ={})
            message = str(raised.exception)
            self.assertIn("target must be relative", message)

    def test_wildcard_and_runtime_specific_destinations_cannot_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = self.make_brain(root)
            profile_path = brain / "_AGENTS" / "SHARED" / "profiles" / "work.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            duplicate = dict(profile["runtime_overlays"][0])
            duplicate["runtime"] = "codex"
            profile["runtime_overlays"].append(duplicate)
            profile_path.write_text(json.dumps(profile), encoding="utf-8")

            with self.assertRaisesRegex(ProfileError, "duplicates target"):
                resolve_profile(brain, environ={})


if __name__ == "__main__":
    unittest.main()

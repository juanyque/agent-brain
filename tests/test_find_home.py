from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FIND_HOME = REPO_ROOT / "skills" / "brain" / "scripts" / "find_home.py"
MODEL_ROOT = REPO_ROOT / "model"


class FindHomeCliTests(unittest.TestCase):
    def run_find_home(
        self,
        *args: str,
        home: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        env = os.environ.copy()
        if home is not None:
            env["HOME"] = str(home)
        result = subprocess.run(
            [sys.executable, str(FIND_HOME), *args],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        payload = json.loads(result.stdout)
        return result, payload

    @staticmethod
    def attach(brain: Path, model: Path = MODEL_ROOT) -> None:
        brain.mkdir(parents=True, exist_ok=True)
        (brain / "_COMMON").symlink_to(model, target_is_directory=True)

    def test_explicit_project_is_candidate_but_not_implanted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "project"
            (project / "WIP").mkdir(parents=True)
            (project / "AGENTS.md").write_text("# Project instructions\n", encoding="utf-8")
            (project / "README.md").write_text("# Project\n", encoding="utf-8")

            strict, strict_payload = self.run_find_home(str(project))
            candidates, candidate_payload = self.run_find_home(
                "--candidates",
                str(project),
            )

        self.assertEqual(strict.returncode, 1, strict.stderr)
        self.assertEqual(strict_payload["count"], 0)
        self.assertEqual(strict_payload["homes"], [])
        self.assertEqual(candidates.returncode, 0, candidates.stderr)
        self.assertEqual(candidate_payload["count"], 1)
        self.assertEqual(candidate_payload["homes"][0]["notes_mode"], "generic")

    def test_missing_path_returns_a_complete_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            missing = Path(raw) / "missing"

            result, payload = self.run_find_home(str(missing))

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(payload["mode"], "implanted")
        self.assertEqual(payload["homes"], [])
        self.assertEqual(payload["conflicts"], [])
        self.assertEqual(payload["expected_model_root"], str(MODEL_ROOT.resolve()))
        self.assertIn("Path does not exist", payload["error"])

    def test_current_model_link_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            valid = root / "valid"
            legacy = root / "legacy"
            old_model = root / "obsidian-vault-common"
            old_model.mkdir()
            self.attach(valid)
            self.attach(legacy, old_model)

            valid_result, valid_payload = self.run_find_home(str(valid))
            legacy_result, legacy_payload = self.run_find_home(str(legacy))

        self.assertEqual(valid_result.returncode, 0, valid_result.stderr)
        self.assertEqual(
            [home["path"] for home in valid_payload["homes"]],
            [str(valid.resolve())],
        )
        self.assertEqual(legacy_result.returncode, 1, legacy_result.stderr)
        self.assertEqual(legacy_payload["homes"], [])
        self.assertEqual(legacy_payload["count"], 0)
        self.assertTrue(legacy_payload["conflicts"])

    def test_broken_looping_and_non_symlink_common_entries_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            broken = root / "broken"
            looping = root / "looping"
            regular = root / "regular"
            broken.mkdir()
            looping.mkdir()
            regular.mkdir()
            (broken / "_COMMON").symlink_to(root / "missing-model", target_is_directory=True)
            (looping / "_COMMON").symlink_to("_COMMON", target_is_directory=True)
            (regular / "_COMMON").mkdir()

            for candidate in (broken, looping, regular):
                with self.subTest(candidate=candidate.name):
                    result, payload = self.run_find_home(str(candidate))
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(payload["homes"], [])
                    self.assertTrue(payload["conflicts"])
                    if candidate in (broken, looping):
                        self.assertEqual(
                            payload["conflicts"][0]["model_status"],
                            "conflict-invalid-target",
                        )

    def test_path_inside_brain_resolves_the_nearest_implanted_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "brain"
            nested_path = brain / "WIP" / "SESSIONS"
            self.attach(brain)
            nested_path.mkdir(parents=True)

            result, payload = self.run_find_home(str(nested_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["homes"][0]["path"], str(brain.resolve()))

    def test_nearer_conflicting_model_blocks_an_outer_valid_brain(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            outer = root / "outer"
            legacy = outer / "legacy"
            nested_path = legacy / "WIP"
            old_model = root / "old-model"
            old_model.mkdir()
            self.attach(outer)
            self.attach(legacy, old_model)
            nested_path.mkdir()

            result, payload = self.run_find_home(str(nested_path))

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(payload["homes"], [])
        self.assertEqual(
            [item["path"] for item in payload["conflicts"]],
            [str(legacy.resolve())],
        )

    def test_global_search_returns_only_implanted_brains_and_preserves_nesting(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            workspace = home / "workspace"
            outer = workspace / "outer"
            inner = outer / "areas" / "inner"
            legacy = workspace / "legacy"
            generic = workspace / "generic"
            old_model = home / "old-model"
            old_model.mkdir()
            self.attach(outer)
            self.attach(inner)
            self.attach(legacy, old_model)
            (generic / "WIP").mkdir(parents=True)
            (generic / "AGENTS.md").write_text("# Project\n", encoding="utf-8")

            result, payload = self.run_find_home(home=home)

        self.assertEqual(result.returncode, 0, result.stderr)
        by_path = {home["path"]: home for home in payload["homes"]}
        self.assertEqual(set(by_path), {str(outer.resolve()), str(inner.resolve())})
        self.assertFalse(by_path[str(outer.resolve())]["is_nested"])
        self.assertTrue(by_path[str(inner.resolve())]["is_nested"])
        self.assertEqual(
            by_path[str(inner.resolve())]["parent_brain"],
            str(outer.resolve()),
        )
        self.assertEqual(
            {item["path"] for item in payload["conflicts"]},
            {str(legacy.resolve())},
        )

    def test_global_search_does_not_follow_directory_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            brain = home / "workspace" / "brain"
            self.attach(brain)
            (home / "alias").symlink_to(brain, target_is_directory=True)

            result, payload = self.run_find_home(home=home)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [item["path"] for item in payload["homes"]],
            [str(brain.resolve())],
        )


if __name__ == "__main__":
    unittest.main()

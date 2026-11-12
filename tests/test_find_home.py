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
        # Hermetic: never read this machine's real HOME or default-brain config.
        env = os.environ.copy()
        env.pop("XDG_CONFIG_HOME", None)
        with tempfile.TemporaryDirectory() as empty_home:
            env["HOME"] = str(home) if home is not None else empty_home
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
    def set_default(home: Path, brain: Path) -> None:
        config = home / ".config" / "agent-brain"
        config.mkdir(parents=True)
        (config / "default_brain.json").write_text(
            json.dumps({"version": 1, "brain": str(brain.resolve())}), encoding="utf-8"
        )

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


    def test_path_inside_brain_reports_ancestor_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "brain"
            self.attach(brain)
            (brain / "WIP").mkdir()

            result, payload = self.run_find_home(str(brain / "WIP"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((payload["status"], payload["source"]), ("resolved", "ancestor"))

    def test_outside_every_brain_uses_the_default_without_scanning(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw) / "home"
            default, other, cwd = home / "ws" / "default", home / "ws" / "other", Path(raw) / "tmp-wt"
            for brain in (default, other):
                self.attach(brain)
            cwd.mkdir()
            self.set_default(home, default)

            result, payload = self.run_find_home(str(cwd), home=home)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((payload["status"], payload["source"]), ("resolved", "default"))
        self.assertEqual([h["path"] for h in payload["homes"]], [str(default.resolve())])

    def test_ancestor_wins_over_the_default(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw) / "home"
            default, local = home / "default", home / "local"
            self.attach(default)
            self.attach(local)
            self.set_default(home, default)

            result, payload = self.run_find_home(str(local), home=home)

        self.assertEqual(payload["source"], "ancestor")
        self.assertEqual([h["path"] for h in payload["homes"]], [str(local.resolve())])

    def test_local_conflict_blocks_default_and_home_scan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw) / "home"
            default, legacy, old_model = home / "default", home / "legacy", home / "old-model"
            old_model.mkdir(parents=True)
            self.attach(default)
            self.attach(legacy, old_model)
            self.set_default(home, default)

            result, payload = self.run_find_home(str(legacy), home=home)

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(payload["status"], "conflict")
        self.assertEqual(payload["homes"], [])

    def test_unusable_default_is_ignored_and_reported(self) -> None:
        cases = {
            "missing-brain": lambda home: json.dumps({"version": 1, "brain": str(home / "gone")}),
            "bad-json": lambda home: "{not json",
            "bad-version": lambda home: json.dumps({"version": 99, "brain": str(home)}),
            "relative": lambda home: json.dumps({"version": 1, "brain": "relative/path"}),
        }
        for name, content in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as raw:
                home, cwd = Path(raw) / "home", Path(raw) / "cwd"
                cwd.mkdir()
                config = home / ".config" / "agent-brain"
                config.mkdir(parents=True)
                (config / "default_brain.json").write_text(content(home), encoding="utf-8")

                result, payload = self.run_find_home("--no-scan", str(cwd), home=home)

                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(payload["status"], "none")
                self.assertIn("default_problem", payload)

    def test_default_pointing_at_a_wrong_model_brain_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home, cwd, old_model = Path(raw) / "home", Path(raw) / "cwd", Path(raw) / "old"
            old_model.mkdir()
            cwd.mkdir()
            legacy = home / "legacy"
            self.attach(legacy, old_model)
            self.set_default(home, legacy)

            result, payload = self.run_find_home("--no-scan", str(cwd), home=home)

        self.assertEqual(payload["status"], "none")
        self.assertIn("default_problem", payload)

    def test_home_scan_resolves_a_single_brain(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home, cwd = Path(raw) / "home", Path(raw) / "cwd"
            brain = home / "ws" / "brain"
            self.attach(brain)
            cwd.mkdir()

            result, payload = self.run_find_home(str(cwd), home=home)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((payload["status"], payload["source"]), ("resolved", "home-scan"))
        self.assertEqual([h["path"] for h in payload["homes"]], [str(brain.resolve())])

    def test_home_scan_with_several_brains_is_ambiguous_and_selects_none(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home, cwd = Path(raw) / "home", Path(raw) / "cwd"
            brains = [home / "a", home / "b"]
            for brain in brains:
                self.attach(brain)
            cwd.mkdir()

            result, payload = self.run_find_home(str(cwd), home=home)

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(payload["status"], "ambiguous")
        self.assertEqual(payload["homes"], [])
        self.assertEqual({c["path"] for c in payload["candidates"]}, {str(b.resolve()) for b in brains})

    def test_home_scan_with_no_brains_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home, cwd = Path(raw) / "home", Path(raw) / "cwd"
            home.mkdir()
            cwd.mkdir()

            result, payload = self.run_find_home(str(cwd), home=home)

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(payload["status"], "none")

    def test_no_scan_never_scans_home(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home, cwd = Path(raw) / "home", Path(raw) / "cwd"
            self.attach(home / "brain")
            cwd.mkdir()

            result, payload = self.run_find_home("--no-scan", str(cwd), home=home)

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(payload["status"], "none")

    def test_all_ignores_the_default_and_deduplicates_overlapping_roots(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw) / "home"
            default, other = home / "ws" / "default", home / "ws" / "other"
            for brain in (default, other):
                self.attach(brain)
            self.set_default(home, default)
            cwd = home / "ws"  # inside HOME, so the subtree and HOME scans overlap

            result, payload = self.run_find_home("--all", str(cwd), home=home)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["source"], "all")
        paths = [h["path"] for h in payload["homes"]]
        self.assertEqual(sorted(paths), sorted([str(default.resolve()), str(other.resolve())]))
        self.assertEqual(len(paths), len(set(paths)))

    def test_all_finds_a_brain_below_the_cwd_outside_home(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home, cwd = Path(raw) / "home", Path(raw) / "cwd"
            home.mkdir()
            nested = cwd / "sub" / "brain"
            self.attach(nested)

            result, payload = self.run_find_home("--all", str(cwd), home=home)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([h["path"] for h in payload["homes"]], [str(nested.resolve())])

    def test_candidates_mode_output_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "project"
            (project / "WIP").mkdir(parents=True)

            result, payload = self.run_find_home("--candidates", str(project))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("status", payload)
        self.assertEqual(payload["mode"], "candidates")


if __name__ == "__main__":
    unittest.main()
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
HOME_SETUP = REPO_ROOT / "model" / "SCRIPTS" / "home_setup.py"
sys.path.insert(0, str(REPO_ROOT / "model" / "SCRIPTS"))

from brain_state import is_linked_worktree  # noqa: E402

GIT = ["git", "-c", "user.email=tests@example.invalid", "-c", "user.name=agent-brain tests"]


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), text=True, capture_output=True, check=False, cwd=cwd)


def find_home(path: Path) -> dict:
    result = run(sys.executable, str(FIND_HOME), str(path))
    return json.loads(result.stdout)


class WorktreeFixture(unittest.TestCase):
    """A fake HOME whose `.local/share/agent-brain` points at this checkout, a primary brain two
    levels below it (so the tracked relative link resolves) and a linked worktree one level deeper."""

    def setUp(self) -> None:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        self.root = Path(raw.name).resolve()
        share = self.root / "home" / ".local" / "share"
        share.mkdir(parents=True)
        (share / "agent-brain").symlink_to(REPO_ROOT, target_is_directory=True)
        self.primary = self.root / "home" / "workspace" / "brain"
        self.primary.mkdir(parents=True)
        run(*GIT, "init", "-q", cwd=self.primary)
        (self.primary / "_COMMON").symlink_to("../../.local/share/agent-brain/model")
        (self.primary / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
        run(*GIT, "add", "-A", cwd=self.primary)
        self.assertEqual(run(*GIT, "commit", "-qm", "init", cwd=self.primary).returncode, 0)
        deeper = self.root / "home" / ".wt" / "deeper"
        deeper.mkdir(parents=True)
        self.worktree = deeper / "brain-wt"
        added = run(*GIT, "worktree", "add", "-q", str(self.worktree), "-b", "wt", cwd=self.primary)
        self.assertEqual(added.returncode, 0, added.stderr)

    def listing(self, path: Path) -> set[str]:
        return {entry.name for entry in path.iterdir()}


class LinkedWorktreeDetectionTests(WorktreeFixture):
    def test_primary_worktree_and_plain_folder(self) -> None:
        self.assertFalse(is_linked_worktree(self.primary))
        self.assertTrue(is_linked_worktree(self.worktree))
        self.assertFalse(is_linked_worktree(self.root))


class FindHomeHintTests(WorktreeFixture):
    def test_the_primary_checkout_is_found_and_the_worktree_is_a_conflict_with_a_hint(self) -> None:
        self.assertEqual(len(find_home(self.primary)["homes"]), 1)

        result = find_home(self.worktree)

        self.assertEqual(result["homes"], [])
        (conflict,) = result["conflicts"]
        self.assertEqual(conflict["model_status"], "conflict-invalid-target")
        self.assertIn("linked git worktree", conflict["hint"])
        self.assertIn("--relink-common", conflict["hint"])
        self.assertIn(str(HOME_SETUP), conflict["hint"])
        self.assertIn(str(self.worktree), conflict["hint"])

    def test_a_dangling_link_outside_a_worktree_gets_the_generic_hint(self) -> None:
        plain = self.root / "plain"
        plain.mkdir()
        (plain / "_COMMON").symlink_to("../nowhere/model")

        (conflict,) = find_home(plain)["conflicts"]

        self.assertIn("target does not exist", conflict["hint"])
        self.assertNotIn("worktree", conflict["hint"])

    def test_other_conflicts_have_no_hint(self) -> None:
        other = self.root / "other-model"
        other.mkdir()
        brain = self.root / "wrong"
        brain.mkdir()
        (brain / "_COMMON").symlink_to(other)

        (conflict,) = find_home(brain)["conflicts"]

        self.assertEqual(conflict["model_status"], "conflict-wrong-target")
        self.assertNotIn("hint", conflict)


class RelinkCommonTests(WorktreeFixture):
    def relink(self, brain: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        env_free = [sys.executable, str(HOME_SETUP), "--brain", str(brain), "--relink-common", *extra]
        return run(*env_free)

    def test_dry_run_changes_nothing(self) -> None:
        before_link = os.readlink(self.worktree / "_COMMON")
        before = self.listing(self.worktree)

        result = self.relink(self.worktree)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dry run only", result.stdout)
        self.assertEqual(os.readlink(self.worktree / "_COMMON"), before_link)
        self.assertEqual(self.listing(self.worktree), before)

    def test_apply_repoints_only_the_link_and_suggests_skip_worktree(self) -> None:
        before = self.listing(self.worktree)

        result = self.relink(self.worktree, "--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RELINKED _COMMON", result.stdout)
        self.assertIn("update-index --skip-worktree _COMMON", result.stdout)
        self.assertEqual(self.listing(self.worktree), before)
        self.assertEqual(len(find_home(self.worktree)["homes"]), 1)
        status = run(*GIT, "status", "--short", cwd=self.worktree).stdout.split()
        self.assertEqual(status, ["M", "_COMMON"])
        self.assertEqual(os.readlink(self.primary / "_COMMON"), "../../.local/share/agent-brain/model")

    def test_a_working_link_needs_nothing(self) -> None:
        result = self.relink(self.primary, "--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing to do", result.stdout)

    def test_a_valid_link_to_another_model_is_refused(self) -> None:
        other = self.root / "other-model"
        other.mkdir()
        brain = self.root / "wrong"
        brain.mkdir()
        (brain / "_COMMON").symlink_to(other)

        result = self.relink(brain, "--apply")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--switch-model", result.stdout + result.stderr)
        self.assertEqual(Path(os.readlink(brain / "_COMMON")), other)

    def test_a_real_directory_named_common_is_refused(self) -> None:
        brain = self.root / "dir"
        (brain / "_COMMON").mkdir(parents=True)

        result = self.relink(brain, "--apply")

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((brain / "_COMMON").is_dir() and not (brain / "_COMMON").is_symlink())

    def test_a_missing_link_is_created_only_in_a_brain_with_wrapper_files(self) -> None:
        bare = self.root / "bare"
        bare.mkdir()
        refused = self.relink(bare, "--apply")
        self.assertNotEqual(refused.returncode, 0)
        self.assertFalse((bare / "_COMMON").exists())

        branded = self.root / "home" / "workspace" / "branded"
        branded.mkdir()
        (branded / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
        created = self.relink(branded, "--apply")
        self.assertEqual(created.returncode, 0, created.stderr + created.stdout)
        self.assertEqual(len(find_home(branded)["homes"]), 1)

    def test_it_cannot_be_combined_with_the_heavy_flags(self) -> None:
        result = self.relink(self.worktree, "--switch-model", "--apply")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot be combined", result.stdout + result.stderr)
        self.assertEqual(self.listing(self.worktree), {"AGENTS.md", "_COMMON", ".git"})


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "model" / "SCRIPTS"
sys.path.insert(0, str(SCRIPTS_DIR))

from _common import Reporter  # noqa: E402
from brain_state import detect_state  # noqa: E402
from home_setup import TEMPLATE_SYMLINKS, WRAPPERS, apply, print_plan  # noqa: E402


def create_common(root: Path) -> Path:
    common = root / "model"
    common.mkdir()
    for common_name in WRAPPERS.values():
        (common / common_name).write_text(f"# {common_name}\n", encoding="utf-8")
    for common_rel in TEMPLATE_SYMLINKS.values():
        path = common / common_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.name}\n", encoding="utf-8")
    task_types = common / "TASK_TYPES"
    task_types.mkdir(exist_ok=True)
    (task_types / "example.common.md").write_text("# example\n", encoding="utf-8")
    return common


def tree_snapshot(root: Path) -> list[tuple[str, str, str]]:
    snapshot: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] == ".git":
            continue
        if path.is_symlink():
            snapshot.append((str(rel), "symlink", os.readlink(path)))
        elif path.is_file():
            snapshot.append((str(rel), "file", path.read_text(encoding="utf-8")))
        elif path.is_dir():
            snapshot.append((str(rel), "dir", ""))
    return snapshot


class BrainStateTests(unittest.TestCase):
    def test_state_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            common = root / "common"
            common.mkdir()

            virgin = root / "virgin"
            virgin.mkdir()
            self.assertEqual(detect_state(virgin, common), "virgin")

            attached_missing = root / "attached-missing"
            attached_missing.mkdir()
            (attached_missing / "AGENTS.md").touch()
            self.assertEqual(
                detect_state(attached_missing, common),
                "attached-link-missing",
            )

            initial = root / "initial"
            initial.mkdir()
            (initial / "_COMMON").symlink_to(common)
            (initial / "_STAGING").mkdir()
            (initial / "_STAGING" / "note.md").touch()
            self.assertEqual(detect_state(initial, common), "initial")

            maintenance = root / "maintenance"
            maintenance.mkdir()
            (maintenance / "_COMMON").symlink_to(common)
            self.assertEqual(detect_state(maintenance, common), "maintenance")

            conflict = root / "conflict"
            conflict.mkdir()
            wrong = root / "wrong"
            wrong.mkdir()
            (conflict / "_COMMON").symlink_to(wrong)
            self.assertEqual(detect_state(conflict, common), "conflict")


class HomeSetupTests(unittest.TestCase):
    def test_conflict_plan_distinguishes_current_and_desired_targets(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            common = create_common(root)
            wrong = root / "old-model"
            wrong.mkdir()

            fixtures = {
                "wrong-symlink": (
                    lambda entry: entry.symlink_to(wrong),
                    ["status: conflict-wrong-target", "current: symlink ->", str(wrong)],
                ),
                "broken-symlink": (
                    lambda entry: entry.symlink_to(root / "missing-model"),
                    [
                        "status: conflict-invalid-target",
                        "current: symlink ->",
                        "target missing",
                        str(root / "missing-model"),
                    ],
                ),
                "regular-file": (
                    lambda entry: entry.write_text("not a link\n", encoding="utf-8"),
                    ["status: conflict-not-symlink", "current: regular file at"],
                ),
            }

            for name, (create_entry, expected) in fixtures.items():
                with self.subTest(name=name):
                    brain = root / name
                    brain.mkdir()
                    create_entry(brain / "_COMMON")
                    reporter = Reporter(root / f"{name}.log")
                    with redirect_stdout(io.StringIO()):
                        print_plan(
                            brain,
                            common,
                            reporter,
                            applied=False,
                            command_string="home_setup.py --dry-run",
                            skip_full_reorder=True,
                        )
                    output = "\n".join(reporter.lines)
                    for fragment in expected:
                        self.assertIn(fragment, output)
                    self.assertIn("desired: symlink ->", output)
                    self.assertIn(str(common.resolve()), output)

    def test_invalid_target_apply_error_uses_the_same_current_and_desired_details(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            common = create_common(root)
            missing = root / "missing-model"
            (brain / "_COMMON").symlink_to(missing)
            reporter = Reporter(root / "home-setup.log")

            with self.assertRaises(SystemExit) as raised:
                apply(brain, common, True, False, reporter)

            message = str(raised.exception)
            self.assertIn("status: conflict-invalid-target", message)
            self.assertIn(f"current: symlink -> {missing}", message)
            self.assertIn("target missing", message)
            self.assertIn("desired: symlink ->", message)
            self.assertIn(str(common.resolve()), message)
            self.assertTrue((brain / "_COMMON").is_symlink())

    def test_attach_preserves_existing_files_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            common = create_common(root)
            (brain / "AGENTS.md").write_text("# private instructions\n", encoding="utf-8")
            daily = brain / "TEMPLATES" / "Daily Note Template.md"
            daily.parent.mkdir()
            daily.write_text("# private daily\n", encoding="utf-8")
            reporter = Reporter(root / "home-setup.log")

            with redirect_stdout(io.StringIO()):
                apply(
                    brain,
                    common,
                    skip_full_reorder=True,
                    switch_model=True,
                    reporter=reporter,
                )
                first = tree_snapshot(brain)
                apply(
                    brain,
                    common,
                    skip_full_reorder=True,
                    switch_model=True,
                    reporter=reporter,
                )
            second = tree_snapshot(brain)
            agents_content = (brain / "AGENTS.md").read_text()
            daily_content = daily.read_text()
            common_ok = (brain / "_COMMON").resolve() == common.resolve()
            brain_wrapper_exists = (brain / "BRAIN.md").is_file()
            wip_template_is_link = (brain / "TEMPLATES" / "WIP Template.md").is_symlink()

        self.assertEqual(first, second)
        self.assertEqual(agents_content, "# private instructions\n")
        self.assertEqual(daily_content, "# private daily\n")
        self.assertTrue(common_ok)
        self.assertTrue(brain_wrapper_exists)
        self.assertTrue(wip_template_is_link)

    def test_conflicting_common_is_backed_up_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            common = create_common(root)
            wrong = root / "old-model"
            wrong.mkdir()
            (brain / "_COMMON").symlink_to(wrong)
            reporter = Reporter(root / "home-setup.log")

            with redirect_stdout(io.StringIO()):
                apply(brain, common, True, True, reporter)
                apply(brain, common, True, True, reporter)
            backups = list(brain.glob("_COMMON.backup-*"))
            common_ok = (brain / "_COMMON").resolve() == common.resolve()
            backup_is_link = len(backups) == 1 and backups[0].is_symlink()
            backup_target_ok = backup_is_link and backups[0].resolve() == wrong.resolve()

        self.assertTrue(common_ok)
        self.assertEqual(len(backups), 1)
        self.assertTrue(backup_is_link)
        self.assertTrue(backup_target_ok)

    def test_virgin_content_moves_to_staging_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            common = create_common(root)
            subprocess.run(["git", "init", "-q"], cwd=brain, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"],
                cwd=brain,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "agent-brain tests"],
                cwd=brain,
                check=True,
            )
            (brain / "notes.md").write_text("private notes\n", encoding="utf-8")
            subprocess.run(["git", "add", "notes.md"], cwd=brain, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=brain, check=True)
            reporter = Reporter(root / "home-setup.log")

            with redirect_stdout(io.StringIO()):
                apply(brain, common, False, True, reporter)
                first = tree_snapshot(brain)
                apply(brain, common, False, True, reporter)
            second = tree_snapshot(brain)
            original_exists = (brain / "notes.md").exists()
            staged_content = (brain / "_STAGING" / "notes.md").read_text(encoding="utf-8")

        self.assertEqual(first, second)
        self.assertFalse(original_exists)
        self.assertEqual(staged_content, "private notes\n")


if __name__ == "__main__":
    unittest.main()

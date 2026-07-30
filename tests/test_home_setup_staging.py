from __future__ import annotations

import io
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME_SETUP_SCRIPT = ROOT / "model" / "SCRIPTS" / "home_setup.py"
BOOTSTRAP_SCRIPT = ROOT / "model" / "SCRIPTS" / "bootstrap-zero.sh"
sys.path.insert(0, str(ROOT / "model" / "SCRIPTS"))

from _common import Reporter  # noqa: E402
from home_setup_filesystem import move_to_staging  # noqa: E402


class HomeSetupStagingTests(unittest.TestCase):
    def test_dry_run_prints_public_apply_command_with_selected_options(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain with spaces"
            home = root / "home"
            brain.mkdir()
            home.mkdir()
            env = os.environ.copy()
            env["HOME"] = str(home)

            result = subprocess.run(
                [
                    "bash",
                    str(BOOTSTRAP_SCRIPT),
                    "--brain",
                    str(brain),
                    "--runtime",
                    "codex",
                    "--symlink-policy",
                    "copy",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=20,
            )
            command_line = next(
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip().startswith("| bash -s --")
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "curl -fsSL https://raw.githubusercontent.com/juanyque/agent-brain/main/bootstrap-zero.sh",
            result.stdout,
        )
        self.assertEqual(
            shlex.split(command_line),
            [
                "|",
                "bash",
                "-s",
                "--",
                "--brain",
                str(brain),
                "--runtime",
                "codex",
                "--symlink-policy",
                "copy",
                "--apply",
            ],
        )

    def test_bootstrap_forwards_copy_policy_to_home_setup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            home = root / "home"
            brain.mkdir()
            home.mkdir()
            external = root / "external.md"
            external.write_text("# External\n", encoding="utf-8")
            (brain / "linked.md").symlink_to(external)
            env = os.environ.copy()
            env["HOME"] = str(home)

            result = subprocess.run(
                [
                    "bash",
                    str(BOOTSTRAP_SCRIPT),
                    "--brain",
                    str(brain),
                    "--runtime",
                    "codex",
                    "--symlink-policy",
                    "copy",
                    "--apply",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=20,
            )
            staged = brain / "_STAGING" / "linked.md"
            staged_is_regular = staged.is_file() and not staged.is_symlink()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(staged_is_regular)

    def test_dry_run_reports_required_symlink_decision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            external = root / "external.md"
            external.write_text("# External\n", encoding="utf-8")
            local_link = brain / "linked.md"
            local_link.symlink_to(external)
            reporter = Reporter(root / "home-setup.log")
            output = io.StringIO()

            with redirect_stdout(output):
                move_to_staging(brain, reporter, dry_run=True)

            self.assertTrue(local_link.is_symlink())
            self.assertFalse((brain / "_STAGING").exists())

        self.assertIn("symlink_policy: required", output.getvalue())
        self.assertIn("symlink: linked.md", output.getvalue())

    def test_cli_accepts_copy_policy_for_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            external = root / "external.md"
            external.write_text("# External\n", encoding="utf-8")
            (brain / "linked.md").symlink_to(external)

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOME_SETUP_SCRIPT),
                    "--brain",
                    str(brain),
                    "--symlink-policy",
                    "copy",
                    "--apply",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            staged = brain / "_STAGING" / "linked.md"
            staged_is_regular = staged.is_file() and not staged.is_symlink()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(staged_is_regular)

    def test_move_requires_policy_for_top_level_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            external = root / "external.md"
            external.write_text("# External\n", encoding="utf-8")
            local_link = brain / "linked.md"
            local_link.symlink_to(external)
            reporter = Reporter(root / "home-setup.log")

            with self.assertRaises(SystemExit):
                with redirect_stdout(io.StringIO()):
                    move_to_staging(brain, reporter, dry_run=False)

            self.assertTrue(local_link.is_symlink())
            self.assertFalse((brain / "_STAGING").exists())

    def test_move_materializes_relative_symlink_to_external_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            external = root / "external" / "source.md"
            external.parent.mkdir()
            external.write_text("# Preserved content\n", encoding="utf-8")
            local_link = brain / "linked.md"
            local_link.symlink_to(Path("..") / "external" / "source.md")
            reporter = Reporter(root / "home-setup.log")

            with redirect_stdout(io.StringIO()):
                move_to_staging(
                    brain,
                    reporter,
                    dry_run=False,
                    symlink_policy="copy",
                )

            staged = brain / "_STAGING" / "linked.md"
            self.assertTrue(staged.is_file())
            self.assertFalse(staged.is_symlink())
            self.assertEqual(staged.read_text(), "# Preserved content\n")
            self.assertEqual(external.read_text(), "# Preserved content\n")

    def test_keep_policy_leaves_symlink_and_stages_regular_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            external = root / "external.md"
            external.write_text("# External\n", encoding="utf-8")
            local_link = brain / "linked.md"
            local_link.symlink_to(external)
            regular = brain / "notes.md"
            regular.write_text("# Notes\n", encoding="utf-8")
            reporter = Reporter(root / "home-setup.log")

            with redirect_stdout(io.StringIO()):
                move_to_staging(
                    brain,
                    reporter,
                    dry_run=False,
                    symlink_policy="keep",
                )

            self.assertTrue(local_link.is_symlink())
            self.assertEqual(local_link.resolve(), external.resolve())
            self.assertFalse(regular.exists())
            self.assertEqual(
                (brain / "_STAGING" / "notes.md").read_text(encoding="utf-8"),
                "# Notes\n",
            )

    def test_keep_policy_rejects_canonical_symlink_before_any_move(self) -> None:
        for canonical_name in ("JOURNAL", "TEMPLATES", "TASK_TYPES"):
            with self.subTest(canonical_name=canonical_name):
                with tempfile.TemporaryDirectory() as raw:
                    root = Path(raw)
                    brain = root / "brain"
                    brain.mkdir()
                    external = root / "external"
                    external.mkdir()
                    canonical_link = brain / canonical_name
                    canonical_link.symlink_to(external, target_is_directory=True)
                    regular = brain / "notes.md"
                    regular.write_text("# Notes\n", encoding="utf-8")
                    reporter = Reporter(root / "home-setup.log")

                    with self.assertRaises(SystemExit):
                        with redirect_stdout(io.StringIO()):
                            move_to_staging(
                                brain,
                                reporter,
                                dry_run=False,
                                symlink_policy="keep",
                            )

                    self.assertTrue(canonical_link.is_symlink())
                    self.assertTrue(regular.is_file())
                    self.assertFalse((brain / "_STAGING").exists())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model" / "SCRIPTS"))

from _common import Reporter  # noqa: E402
from home_setup_filesystem import move_to_staging  # noqa: E402


class HomeSetupBrokenSymlinkTests(unittest.TestCase):
    def test_dry_run_marks_cyclic_target_as_blocking_copy(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            cyclic = brain / "cycle"
            cyclic.symlink_to(cyclic.name)
            output = io.StringIO()

            with redirect_stdout(output):
                move_to_staging(
                    brain,
                    Reporter(root / "home-setup.log"),
                    dry_run=True,
                )

            self.assertTrue(cyclic.is_symlink())
            self.assertFalse((brain / "_STAGING").exists())

        self.assertIn("copy: blocked-cycle", output.getvalue())
        self.assertIn(
            "recommended_symlink_policy: repair-cycle-then-copy",
            output.getvalue(),
        )

    def test_copy_rejects_cycle_before_moving_regular_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            regular = brain / "a-note.md"
            regular.write_text("# Notes\n", encoding="utf-8")
            cyclic = brain / "z-cycle"
            cyclic.symlink_to(cyclic.name)

            with self.assertRaises(SystemExit):
                with redirect_stdout(io.StringIO()):
                    move_to_staging(
                        brain,
                        Reporter(root / "home-setup.log"),
                        dry_run=False,
                        symlink_policy="copy",
                    )

            self.assertTrue(regular.is_file())
            self.assertTrue(cyclic.is_symlink())
            self.assertFalse((brain / "_STAGING").exists())

    def test_dry_run_marks_missing_target_as_blocking_copy(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            broken = brain / "broken.md"
            broken.symlink_to(Path("..") / "missing.md")
            output = io.StringIO()

            with redirect_stdout(output):
                move_to_staging(
                    brain,
                    Reporter(root / "home-setup.log"),
                    dry_run=True,
                )

            self.assertTrue(broken.is_symlink())
            self.assertFalse((brain / "_STAGING").exists())

        self.assertIn("copy: blocked-missing-target", output.getvalue())
        self.assertIn(
            "recommended_symlink_policy: repair-target-then-copy",
            output.getvalue(),
        )

    def test_copy_rejects_missing_target_before_moving_regular_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            regular = brain / "a-note.md"
            regular.write_text("# Notes\n", encoding="utf-8")
            broken = brain / "z-broken.md"
            broken.symlink_to(Path("..") / "missing.md")

            with self.assertRaisesRegex(
                SystemExit,
                "Cannot copy symlinks with missing targets: z-broken.md",
            ):
                with redirect_stdout(io.StringIO()):
                    move_to_staging(
                        brain,
                        Reporter(root / "home-setup.log"),
                        dry_run=False,
                        symlink_policy="copy",
                    )

            self.assertTrue(regular.is_file())
            self.assertTrue(broken.is_symlink())
            self.assertFalse((brain / "_STAGING").exists())

    def test_keep_leaves_broken_noncanonical_symlink_and_stages_regular_content(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            regular = brain / "notes.md"
            regular.write_text("# Notes\n", encoding="utf-8")
            broken = brain / "broken.md"
            broken.symlink_to(Path("..") / "missing.md")

            with redirect_stdout(io.StringIO()):
                move_to_staging(
                    brain,
                    Reporter(root / "home-setup.log"),
                    dry_run=False,
                    symlink_policy="keep",
                )

            self.assertTrue(broken.is_symlink())
            self.assertFalse(regular.exists())
            self.assertEqual(
                (brain / "_STAGING" / "notes.md").read_text(encoding="utf-8"),
                "# Notes\n",
            )


if __name__ == "__main__":
    unittest.main()

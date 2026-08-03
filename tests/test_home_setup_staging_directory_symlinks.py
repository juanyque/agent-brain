from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME_SETUP_SCRIPT = ROOT / "model" / "SCRIPTS" / "home_setup.py"


class HomeSetupStagingDirectorySymlinkTests(unittest.TestCase):
    def test_copy_policy_materializes_relative_directory_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            external = root / "external" / "linked-notes"
            nested = external / "projects" / "active.md"
            brain.mkdir()
            nested.parent.mkdir(parents=True)
            nested.write_text("# Active project\n", encoding="utf-8")
            local_link = brain / "linked-notes"
            local_link.symlink_to(
                Path("..") / "external" / "linked-notes",
                target_is_directory=True,
            )

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
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            staged = brain / "_STAGING" / "linked-notes"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(staged.is_dir())
            self.assertFalse(staged.is_symlink())
            self.assertFalse(local_link.exists())
            self.assertEqual(
                (staged / "projects" / "active.md").read_text(encoding="utf-8"),
                "# Active project\n",
            )
            self.assertEqual(nested.read_text(encoding="utf-8"), "# Active project\n")


if __name__ == "__main__":
    unittest.main()

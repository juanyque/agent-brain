from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "model" / "SCRIPTS"
sys.path.insert(0, str(SCRIPTS_DIR))

from _common import Reporter  # noqa: E402
from home_setup import apply  # noqa: E402


SCAFFOLD_DIRECTORIES = (
    "INBOX",
    "WIP",
    "WIP/SESSIONS",
    "JOURNAL",
    "MEMORY",
    "BACKLOG",
    "ARCHIVED",
    "REPORTS",
    "OUTBOX",
    "QUARANTINE",
    "QUARANTINE/TRASH",
    "QUARANTINE/ATTACHMENTS",
)


class HomeSetupScaffoldingTests(unittest.TestCase):
    def test_apply_creates_every_content_directory(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            common = root / "model"
            common.mkdir()
            reporter = Reporter(root / "home-setup.log")

            # When
            apply(brain, common, True, True, reporter)

            # Then
            missing = [
                name
                for name in SCAFFOLD_DIRECTORIES
                if not (brain / name).is_dir()
            ]

        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()

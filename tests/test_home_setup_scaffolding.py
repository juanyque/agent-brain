from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "model" / "SCRIPTS"
sys.path.insert(0, str(SCRIPTS_DIR))

from _common import Reporter  # noqa: E402
from home_setup import apply  # noqa: E402
from home_setup_filesystem import cleanup_empty_dirs_recursively  # noqa: E402


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
    "SCRIPTS",
    "SOURCE_TYPES",
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

    def test_empty_directory_cleanup_preserves_canonical_scaffolding(self) -> None:
        # Given: an attached brain whose canonical scaffolding is empty.
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            for name in SCAFFOLD_DIRECTORIES:
                (brain / name).mkdir(parents=True, exist_ok=True)
            removable = brain / "temporary-empty"
            removable.mkdir()
            reporter = Reporter(root / "home-setup.log")

            # When: maintenance removes empty non-canonical directories.
            cleanup_empty_dirs_recursively(brain, reporter, dry_run=False)

            # Then: every canonical directory survives and incidental noise does not.
            missing = [
                name
                for name in SCAFFOLD_DIRECTORIES
                if not (brain / name).is_dir()
            ]

        self.assertEqual(missing, [])
        self.assertFalse(removable.exists())


if __name__ == "__main__":
    unittest.main()

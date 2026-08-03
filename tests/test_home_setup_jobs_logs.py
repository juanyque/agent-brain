from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from tests import test_home_setup as cases


EXPECTED_JOB_SECTIONS = (
    "Daily (Day change)",
    "Session consolidation",
    "Weekly",
    "Monthly",
    "Yearly",
)


class HomeSetupJobsLogsTests(unittest.TestCase):
    def test_dry_run_lists_missing_jobs_log_without_creating_it(self) -> None:
        # Given: a brain without local maintenance execution state.
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            common = cases.create_common(root)
            reporter = cases.Reporter(root / "home-setup.log")

            # When: the setup plan is rendered without applying it.
            with redirect_stdout(StringIO()):
                cases.print_plan(
                    brain,
                    common,
                    reporter,
                    applied=False,
                    command_string="home_setup.py",
                    skip_full_reorder=True,
                )
            listed = "JOBS_LOGS.md" in "\n".join(reporter.lines)
            exists_after = (brain / "JOBS_LOGS.md").exists()

        # Then: the local state path is listed but remains absent.
        self.assertTrue(listed)
        self.assertFalse(exists_after)

    def test_apply_creates_jobs_log_with_scheduler_sections(self) -> None:
        # Given: a brain without local maintenance execution state.
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            common = cases.create_common(root)
            reporter = cases.Reporter(root / "home-setup.log")

            # When: safe setup changes are applied.
            with redirect_stdout(StringIO()):
                cases.apply(
                    brain,
                    common,
                    skip_full_reorder=True,
                    switch_model=True,
                    reporter=reporter,
                )
            jobs_log = brain / "JOBS_LOGS.md"
            headings = tuple(
                line.removeprefix("## ")
                for line in jobs_log.read_text(encoding="utf-8").splitlines()
                if line.startswith("## ")
            )
            is_file = jobs_log.is_file()
            is_symlink = jobs_log.is_symlink()

        # Then: a regular local file exposes every scheduler section without entries.
        self.assertTrue(is_file)
        self.assertFalse(is_symlink)
        self.assertEqual(headings, EXPECTED_JOB_SECTIONS)

    def test_apply_preserves_existing_jobs_log(self) -> None:
        # Given: a brain with user-managed maintenance execution state.
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            common = cases.create_common(root)
            jobs_log = brain / "JOBS_LOGS.md"
            original = "# Private jobs log\n\n## Weekly\n- local history\n"
            jobs_log.write_text(original, encoding="utf-8")
            reporter = cases.Reporter(root / "home-setup.log")

            # When: safe setup changes are applied.
            with redirect_stdout(StringIO()):
                cases.apply(
                    brain,
                    common,
                    skip_full_reorder=True,
                    switch_model=True,
                    reporter=reporter,
                )
            preserved = jobs_log.read_text(encoding="utf-8")

        # Then: the existing local state remains byte-for-byte unchanged.
        self.assertEqual(preserved, original)


if __name__ == "__main__":
    unittest.main()

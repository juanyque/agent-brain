from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from tests import test_home_setup as cases


class HomeSetupObjectivesTests(unittest.TestCase):
    def test_dry_run_lists_missing_objectives_wrapper_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            common = cases.create_common(root)
            reporter = cases.Reporter(root / "home-setup.log")

            with redirect_stdout(StringIO()):
                cases.print_plan(
                    brain,
                    common,
                    reporter,
                    applied=False,
                    command_string="home_setup.py",
                    skip_full_reorder=True,
                )
            listed = "WIP/OBJECTIVES.md" in "\n".join(reporter.lines)
            exists_after = (brain / "WIP" / "OBJECTIVES.md").exists()

        self.assertTrue(listed)
        self.assertFalse(exists_after)

    def test_apply_creates_objectives_wrapper_pointing_at_common(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            common = cases.create_common(root)
            reporter = cases.Reporter(root / "home-setup.log")

            with redirect_stdout(StringIO()):
                cases.apply(
                    brain,
                    common,
                    skip_full_reorder=True,
                    switch_model=True,
                    reporter=reporter,
                )
            wrapper = brain / "WIP" / "OBJECTIVES.md"
            content = wrapper.read_text(encoding="utf-8") if wrapper.exists() else ""
            is_file = wrapper.is_file()
            is_symlink = wrapper.is_symlink()

        self.assertTrue(is_file)
        self.assertFalse(is_symlink)
        self.assertIn("[[_COMMON/OBJECTIVES.common.md]]", content)
        self.assertIn("## Objetivos locales", content)
        self.assertIn("[[Learn]]", content)
        self.assertIn("[[Collaborate]]", content)

    def test_apply_preserves_existing_rich_objectives_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            common = cases.create_common(root)
            objectives = brain / "WIP" / "OBJECTIVES.md"
            original = (
                "---\ntags: [wip, objectives]\n---\n"
                "# OBJECTIVES\n\n"
                "## Objetivos activos\n\n- [[Team CR]] — review\n"
            )
            objectives.parent.mkdir(parents=True, exist_ok=True)
            objectives.write_text(original, encoding="utf-8")
            reporter = cases.Reporter(root / "home-setup.log")

            with redirect_stdout(StringIO()):
                cases.apply(
                    brain,
                    common,
                    skip_full_reorder=True,
                    switch_model=True,
                    reporter=reporter,
                )
            preserved = objectives.read_text(encoding="utf-8")

        self.assertEqual(preserved, original)


if __name__ == "__main__":
    unittest.main()

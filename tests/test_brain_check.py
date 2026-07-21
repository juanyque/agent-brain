from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "brain" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from brain_check import validate_wip_registration  # noqa: E402


class BrainCheckTests(unittest.TestCase):
    def test_registered_wip_note_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            (brain / "WIP").mkdir()
            (brain / "WIP" / "agent-brain.md").write_text("# agent-brain\n")
            (brain / "WIP" / "WIP.md").write_text(
                "# WIP\n- [[agent-brain]] — active\n",
                encoding="utf-8",
            )
            errors = validate_wip_registration(brain, "WIP/agent-brain.md")
        self.assertEqual(errors, [])

    def test_unregistered_wip_note_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            (brain / "WIP").mkdir()
            (brain / "WIP" / "agent-brain.md").write_text("# agent-brain\n")
            (brain / "WIP" / "WIP.md").write_text("# WIP\n", encoding="utf-8")
            errors = validate_wip_registration(brain, "WIP/agent-brain.md")
        self.assertTrue(any("not registered" in error for error in errors))

    def test_markdown_link_registration_passes_for_generic_brain(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            (brain / "WIP" / "projects").mkdir(parents=True)
            (brain / "WIP" / "projects" / "agent-brain.md").write_text(
                "# agent-brain\n",
                encoding="utf-8",
            )
            (brain / "WIP" / "WIP.md").write_text(
                "# WIP\n- [agent-brain](projects/agent-brain.md) — active\n",
                encoding="utf-8",
            )
            errors = validate_wip_registration(
                brain,
                "WIP/projects/agent-brain.md",
            )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()

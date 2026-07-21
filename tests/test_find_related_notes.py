from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "brain"
    / "scripts"
    / "find_related_notes.py"
)


class FindRelatedNotesCliTests(unittest.TestCase):
    def test_existing_brain_returns_matching_notes_in_all_modes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            note = brain / "WIP" / "agent-brain-roadmap.md"
            note.parent.mkdir()
            note.write_text(
                "# Agent brain roadmap\n\nTracks agent-brain work.\n",
                encoding="utf-8",
            )

            expected_sources = {
                "filename": "filename",
                "content": "content",
                "both": "filename+content",
            }
            for mode, expected_source in expected_sources.items():
                with self.subTest(mode=mode):
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(SCRIPT),
                            "--brain",
                            str(brain),
                            "--keywords",
                            "agent-brain",
                            "--mode",
                            mode,
                        ],
                        text=True,
                        capture_output=True,
                        check=False,
                    )

                    self.assertEqual(result.returncode, 0, result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertEqual(payload["vault"], str(brain.resolve()))
                    self.assertEqual(payload["count"], 1)
                    self.assertEqual(
                        payload["notes"][0]["relative_path"],
                        "WIP/agent-brain-roadmap.md",
                    )
                    self.assertEqual(
                        payload["notes"][0]["match_source"],
                        expected_source,
                    )

    def test_missing_brain_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "missing"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--brain",
                    str(brain),
                    "--keywords",
                    "agent-brain",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["vault"], str(brain.resolve()))
        self.assertEqual(payload["count"], 0)
        self.assertIn("Brain path does not exist", payload["error"])


if __name__ == "__main__":
    unittest.main()

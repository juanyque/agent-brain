from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "boyscout"
DOCTOR = SKILL_DIR / "scripts" / "doctor.py"


class BoyscoutDoctorTests(unittest.TestCase):
    def run_doctor(
        self, skill_dir: Path, backlog: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(DOCTOR),
                "--skill-dir",
                str(skill_dir),
                "--backlog",
                str(backlog),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_public_reference_names_pass_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = self.run_doctor(
                SKILL_DIR,
                Path(raw) / "missing-backlog.md",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("boyscout doctor: OK", result.stdout)

    def test_doctor_rejects_broken_links_and_private_layout_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = root / "boyscout"
            shutil.copytree(SKILL_DIR, fixture)
            deep_mode = fixture / "references" / "deep-mode.md"
            deep_mode.write_text(
                deep_mode.read_text(encoding="utf-8")
                + "\n[Missing contract](missing-contract.md)\n"
                + "Legacy entrypoint: `SKILL.boyscout.md`.\n",
                encoding="utf-8",
            )

            result = self.run_doctor(fixture, root / "missing-backlog.md")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("FAIL  local Markdown links", result.stdout)
            self.assertIn("missing-contract.md", result.stdout)
            self.assertIn("FAIL  public migration artifacts", result.stdout)
            self.assertIn("SKILL.boyscout.md", result.stdout)


if __name__ == "__main__":
    unittest.main()

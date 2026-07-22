from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "boyscout"
DOCTOR = SKILL_DIR / "scripts" / "doctor.py"


class BoyscoutDoctorTests(unittest.TestCase):
    def test_public_reference_names_pass_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = subprocess.run(
                [
                    sys.executable,
                    str(DOCTOR),
                    "--skill-dir",
                    str(SKILL_DIR),
                    "--backlog",
                    str(Path(raw) / "missing-backlog.md"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("boyscout doctor: OK", result.stdout)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OPERATING_MODEL = REPO_ROOT / "model" / "OPERATING-MODEL.json"


class ScopeContractTests(unittest.TestCase):
    def test_public_bootstrap_is_inside_governed_scope(self) -> None:
        model = json.loads(OPERATING_MODEL.read_text(encoding="utf-8"))

        self.assertIn("bootstrap-zero.sh", model["scope"]["allow"])


if __name__ == "__main__":
    unittest.main()

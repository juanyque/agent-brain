from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from tests import test_home_setup as cases


class HomeSetupEvidenceStoreTests(unittest.TestCase):
    def test_apply_scaffolds_the_evidence_store_and_its_attachments_dir(self) -> None:
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
            store = brain / "WIP" / "evidence"
            attachments = store / "ATTACHMENTS"
            store_exists = store.is_dir()
            attachments_exists = attachments.is_dir()

        self.assertTrue(store_exists, "WIP/evidence/ must exist right after setup")
        self.assertTrue(
            attachments_exists,
            "WIP/evidence/ATTACHMENTS/ must exist right after setup",
        )


if __name__ == "__main__":
    unittest.main()

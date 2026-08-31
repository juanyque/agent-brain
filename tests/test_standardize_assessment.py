from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "brain" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
loaded_common = sys.modules.get("_common")
if loaded_common is not None:
    loaded_path = getattr(loaded_common, "__file__", "")
    if loaded_path and Path(loaded_path).resolve().parent != SCRIPTS_DIR:
        del sys.modules["_common"]

from standardize_assessment import EXPECTED_ROOT_FILES, assess_root  # noqa: E402

sys.path.remove(str(SCRIPTS_DIR))
if loaded_common is None:
    sys.modules.pop("_common", None)
else:
    sys.modules["_common"] = loaded_common


LEGACY_REQUIRED_ROOT_DIRS = {
    "_COMMON",
    "BACKLOG",
    "INBOX",
    "JOURNAL",
    "MEMORY",
    "QUARANTINE",
    "REPORTS",
    "TEMPLATES",
    "WIP",
}
NEW_REQUIRED_ROOT_DIRS = {
    "ARCHIVED",
    "OUTBOX",
    "SCRIPTS",
    "SOURCE_TYPES",
    "TASK_TYPES",
}
OPTIONAL_ROOT_DIRS = {"_AGENTS", "_STAGING"}


def create_root_entries(root: Path, directories: set[str]) -> None:
    for directory in directories:
        (root / directory).mkdir()
    for filename in EXPECTED_ROOT_FILES:
        (root / filename).write_text("", encoding="utf-8")


class StandardizeAssessmentRootTests(unittest.TestCase):
    def test_reports_missing_wrapper_for_discovered_common_rule(self) -> None:
        # Given: a canonical common rule without its brain-local wrapper.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            create_root_entries(
                brain,
                LEGACY_REQUIRED_ROOT_DIRS | NEW_REQUIRED_ROOT_DIRS,
            )
            (brain / "_COMMON" / "RULES-FUTURE.common.md").write_text(
                "# Future rule\n",
                encoding="utf-8",
            )

            # When: the root structure is assessed.
            findings = assess_root(brain)

        # Then: the discovered wrapper is reported as missing.
        self.assertIn(
            "Missing expected file `RULES-FUTURE.md`.",
            {finding.message for finding in findings},
        )

    def test_accepts_wrapper_for_discovered_common_rule(self) -> None:
        # Given: a canonical common rule and its matching brain-local wrapper.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            create_root_entries(
                brain,
                LEGACY_REQUIRED_ROOT_DIRS | NEW_REQUIRED_ROOT_DIRS,
            )
            (brain / "_COMMON" / "RULES-FUTURE.common.md").write_text(
                "# Future rule\n",
                encoding="utf-8",
            )
            (brain / "RULES-FUTURE.md").write_text("# Local wrapper\n", encoding="utf-8")

            # When: the root structure is assessed.
            findings = assess_root(brain)

        # Then: the discovered wrapper is accepted as canonical.
        self.assertEqual(findings, [])

    def test_accepts_required_and_optional_canonical_directories(self) -> None:
        # Given: a brain containing every required and optional canonical root directory.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            create_root_entries(
                brain,
                LEGACY_REQUIRED_ROOT_DIRS | NEW_REQUIRED_ROOT_DIRS | OPTIONAL_ROOT_DIRS,
            )

            # When: its root structure is assessed.
            findings = assess_root(brain)

        # Then: no canonical directory is reported as missing or unexpected.
        self.assertEqual(findings, [])

    def test_requires_new_content_roots_but_not_optional_operational_roots(self) -> None:
        # Given: a legacy brain with the old required root inventory only.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            create_root_entries(brain, LEGACY_REQUIRED_ROOT_DIRS)

            # When: its root structure is assessed.
            findings = assess_root(brain)

        # Then: only the newly required content roots are reported as missing.
        self.assertEqual(
            {finding.message for finding in findings},
            {
                "Missing expected directory `ARCHIVED/`.",
                "Missing expected directory `OUTBOX/`.",
                "Missing expected directory `SCRIPTS/`.",
                "Missing expected directory `SOURCE_TYPES/`.",
                "Missing expected directory `TASK_TYPES/`.",
            },
        )


if __name__ == "__main__":
    unittest.main()

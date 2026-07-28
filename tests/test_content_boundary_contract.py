from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "model" / "SCRIPTS"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from model_check_content_boundaries import (  # noqa: E402
    content_boundary_findings,
    startup_boundary_findings,
    task_type_index_targets,
)


class ContentBoundaryContractTests(unittest.TestCase):
    def test_missing_task_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            task_dir = root / "model" / "TASK_TYPES"
            task_dir.mkdir(parents=True)
            (task_dir / "TASK_TYPES.common.md").write_text(
                "# TASK_TYPES\n\n## Entries\n\n"
                "- [[fixture-task]] - Missing guide.\n",
                encoding="utf-8",
            )

            findings = content_boundary_findings(root)

        self.assertEqual([finding.code for finding in findings], ["missing-task-target"])
        self.assertEqual(findings[0].path, "model/TASK_TYPES/TASK_TYPES.common.md")
        self.assertEqual(findings[0].target, "model/TASK_TYPES/fixture-task.common.md")

    def test_duplicate_policy_owner_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model = root / "model"
            model.mkdir()
            (model / "RULES-FILE-NAMING.common.md").write_text(
                '<!-- content-boundary: {"kind":"policy-owner",'
                '"policy_id":"policy.file-naming",'
                '"owner":"model/RULES-FILE-NAMING.common.md"} -->\n',
                encoding="utf-8",
            )
            (model / "RULES-ISSUE-DOCS.common.md").write_text(
                '<!-- content-boundary: {"kind":"policy-owner",'
                '"policy_id":"policy.file-naming",'
                '"owner":"model/RULES-ISSUE-DOCS.common.md"} -->\n',
                encoding="utf-8",
            )

            findings = content_boundary_findings(root)

        self.assertEqual([finding.code for finding in findings], ["duplicate-policy-owner"])
        self.assertEqual(findings[0].target, "policy.file-naming")

    def test_optional_capabilities_are_excluded_from_startup_payloads(self) -> None:
        clean = startup_boundary_findings(ROOT, startup_payloads=())
        leaked = startup_boundary_findings(
            ROOT,
            startup_payloads=("model/TEMPLATES/TEMPLATE.graphify-project.common.md",),
        )

        self.assertEqual(clean, [])
        self.assertEqual([finding.code for finding in leaked], ["eager-optional-capability"])
        self.assertEqual(
            leaked[0].path,
            "model/TEMPLATES/TEMPLATE.graphify-project.common.md",
        )

    def test_current_task_type_index_entries_resolve(self) -> None:
        targets = task_type_index_targets(ROOT)

        self.assertGreater(len(targets), 0)
        self.assertTrue(all(target.path.exists() for target in targets))


if __name__ == "__main__":
    unittest.main()

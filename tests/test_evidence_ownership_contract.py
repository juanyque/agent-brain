from __future__ import annotations

import unittest
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "model" / "RULES-REVIEW-EVIDENCE.common.md"
SCRIPTS = ROOT / "model" / "SCRIPTS"
TEMPLATES = ROOT / "model" / "TEMPLATES"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def template_frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return values
        if ":" not in line:
            continue
        key, value = line.split(":", maxsplit=1)
        values[key.strip()] = value.strip()
    return values


class EvidenceOwnershipBaselineTests(unittest.TestCase):
    def test_existing_review_rule_names_lifecycle_and_archive_destination(self) -> None:
        text = RULES.read_text(encoding="utf-8")

        self.assertIn("ARCHIVED/Reviews/", text)
        self.assertIn("Evidence notes are **append-only and permanent**", text)
        self.assertIn("Sensitive flag", text)

    def test_existing_report_templates_have_initial_status_shape(self) -> None:
        self.assertEqual(
            {
                "TEMPLATE.brag-report.common.md": "draft",
                "TEMPLATE.feedback-report.common.md": "draft",
                "TEMPLATE.complaint-report.common.md": "open",
            },
            {
                name: template_frontmatter(TEMPLATES / name).get("status")
                for name in (
                    "TEMPLATE.brag-report.common.md",
                    "TEMPLATE.feedback-report.common.md",
                    "TEMPLATE.complaint-report.common.md",
                )
            },
        )


class EvidenceOwnershipContractTests(unittest.TestCase):
    def fixture_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        raw = tempfile.TemporaryDirectory()
        root = Path(raw.name)
        shutil.copytree(ROOT / "model", root / "model")
        return raw, root

    def finding_codes(self, root: Path) -> list[str]:
        from model_check_evidence_ownership import scan_evidence_ownership

        return [finding.code for finding in scan_evidence_ownership(root)]

    def test_accepts_current_evidence_ownership_contract(self) -> None:
        codes = self.finding_codes(ROOT)

        self.assertEqual(codes, [])

    def test_rejects_divergent_review_archive_destination_and_unknown_status(self) -> None:
        raw, root = self.fixture_root()
        with raw:
            rules = root / "model" / "RULES-REVIEW-EVIDENCE.common.md"
            rules.write_text(
                rules.read_text(encoding="utf-8").replace(
                    '"archive_destination": "ARCHIVED/Reviews/"',
                    '"archive_destination": "ARCHIVED/Reports/"',
                ),
                encoding="utf-8",
            )
            template = root / "model" / "TEMPLATES" / "TEMPLATE.brag-report.common.md"
            template.write_text(
                template.read_text(encoding="utf-8").replace(
                    "status: draft",
                    "status: published",
                ),
                encoding="utf-8",
            )

            codes = self.finding_codes(root)

        self.assertEqual(codes, ["review-archive-destination", "unknown-review-status"])

    def test_rejects_duplicate_evidence_lifecycle_owner(self) -> None:
        raw, root = self.fixture_root()
        with raw:
            task_type = root / "model" / "TASK_TYPES" / "brag-report.common.md"
            task_type.write_text(
                task_type.read_text(encoding="utf-8")
                + "\n```json evidence-ownership\n"
                + '{"schema_version":"agent-brain-evidence-ownership/v1","owner":"model/TASK_TYPES/brag-report.common.md"}'
                + "\n```\n",
                encoding="utf-8",
            )

            codes = self.finding_codes(root)

        self.assertEqual(codes, ["duplicate-policy-owner"])


if __name__ == "__main__":
    unittest.main()

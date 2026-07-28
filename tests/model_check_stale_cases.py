from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "model" / "SCRIPTS"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from model_check_stale import scan_stale_references


REMOVED_SKILL_TREE = "SKILLS" + "/" + "obsidian"
OLD_DAILY_TEMPLATE = "TEMPLATE.daily-note" + ".md"
REVIEW_REPORTS_ARCHIVE = "ARCHIVED" + "/Reports/"


def write_model(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "finding_contract": {
                    "code_metadata": [
                        {
                            "code": "stale-architecture-reference",
                            "family": "stale-reference",
                            "severity": "error",
                        },
                        {
                            "code": "missing-target",
                            "family": "target-existence",
                            "severity": "error",
                        },
                        {
                            "code": "review-archive-destination",
                            "family": "review-archive",
                            "severity": "error",
                        },
                    ]
                },
                "stale_reference_contract": {
                    "allowlist": [
                        {
                            "id": "allow.history",
                            "path": "history.md",
                            "patterns": [REMOVED_SKILL_TREE],
                            "reason": "historical context",
                        },
                        {
                            "id": "allow.omo-history",
                            "path": ".omo/history.md",
                            "patterns": [REMOVED_SKILL_TREE],
                            "reason": "historical context",
                        }
                    ],
                    "classes": [
                        {
                            "id": "stale-class.removed-obsidian-skill-tree",
                            "patterns": [REMOVED_SKILL_TREE],
                            "reason": "removed skill tree",
                            "replacement": "skills/brain",
                        },
                        {
                            "id": "missing-target.daily-template-basename",
                            "patterns": [OLD_DAILY_TEMPLATE],
                            "reason": "missing common suffix",
                            "replacement": "model/TEMPLATES/TEMPLATE.daily-note.common.md",
                        },
                        {
                            "id": "review-archive.destination",
                            "patterns": [REVIEW_REPORTS_ARCHIVE],
                            "reason": "review reports archive under Reviews",
                            "replacement": "ARCHIVED/Reviews/",
                        },
                    ],
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


class StaleReferenceHelperTests(unittest.TestCase):
    def test_constructed_stale_fixture_identifiers_match_detector_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model = root / "model/OPERATING-MODEL.json"
            write_model(model)
            (root / "doc.md").write_text(
                "\n".join(
                    [
                        f"Use {REMOVED_SKILL_TREE} for tools.",
                        f"Daily shape is {OLD_DAILY_TEMPLATE}.",
                        f"Archive to {REVIEW_REPORTS_ARCHIVE}report.md.",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            findings = scan_stale_references(root, model)

        self.assertEqual(
            [REMOVED_SKILL_TREE, OLD_DAILY_TEMPLATE, REVIEW_REPORTS_ARCHIVE],
            [
                "SKILLS" + "/" + "obsidian",
                "TEMPLATE.daily-note" + ".md",
                "ARCHIVED" + "/Reports/",
            ],
        )
        self.assertEqual(
            {finding.target for finding in findings},
            {REMOVED_SKILL_TREE, OLD_DAILY_TEMPLATE, REVIEW_REPORTS_ARCHIVE},
        )

    def test_classifies_stale_missing_and_review_archive_hits(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model = root / "model/OPERATING-MODEL.json"
            write_model(model)
            (root / "doc.md").write_text(
                "\n".join(
                    [
                        f"Use {REMOVED_SKILL_TREE} for tools.",
                        f"Daily shape is {OLD_DAILY_TEMPLATE}.",
                        f"Archive to {REVIEW_REPORTS_ARCHIVE}report.md.",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            findings = scan_stale_references(root, model)
            rows = [finding.as_json() for finding in findings]

        self.assertEqual(
            [row["code"] for row in rows],
            [
                "missing-target",
                "review-archive-destination",
                "stale-architecture-reference",
            ],
        )
        self.assertEqual(
            {row["family"] for row in rows},
            {"review-archive", "stale-reference", "target-existence"},
        )
        self.assertEqual({tuple(row) for row in rows}, {(
            "code",
            "family",
            "severity",
            "path",
            "target",
            "message",
        )})
        self.assertEqual([row["path"] for row in rows], ["doc.md", "doc.md", "doc.md"])
        self.assertEqual(
            [row["target"] for row in rows],
            [OLD_DAILY_TEMPLATE, REVIEW_REPORTS_ARCHIVE, REMOVED_SKILL_TREE],
        )

    def test_allowlist_suppresses_only_matching_path_and_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model = root / "model/OPERATING-MODEL.json"
            write_model(model)
            (root / "history.md").write_text(f"{REMOVED_SKILL_TREE}\n", encoding="utf-8")
            (root / "live.md").write_text(f"{REMOVED_SKILL_TREE}\n", encoding="utf-8")

            findings = scan_stale_references(root, model)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].path, "live.md")
        self.assertEqual(findings[0].target, REMOVED_SKILL_TREE)

    def test_omo_markdown_is_scanned_unless_exact_allowlist_matches(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model = root / "model/OPERATING-MODEL.json"
            write_model(model)
            (root / ".omo").mkdir()
            (root / ".omo/history.md").write_text(
                f"{REMOVED_SKILL_TREE}\n",
                encoding="utf-8",
            )
            (root / ".omo/live.md").write_text(f"{REMOVED_SKILL_TREE}\n", encoding="utf-8")

            findings = scan_stale_references(root, model)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].path, ".omo/live.md")
        self.assertEqual(findings[0].target, REMOVED_SKILL_TREE)

    def test_cli_strict_json_and_text_are_stable_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model = root / "model/OPERATING-MODEL.json"
            write_model(model)
            doc = root / "doc.md"
            doc.write_text(f"{REVIEW_REPORTS_ARCHIVE}report.md\n", encoding="utf-8")
            before = doc.read_bytes()

            json_result = subprocess.run(
                [
                    "python3",
                    str(SCRIPTS / "model_check_stale.py"),
                    "--root",
                    str(root),
                    "--model",
                    str(model),
                    "--strict",
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            text_result = subprocess.run(
                [
                    "python3",
                    str(SCRIPTS / "model_check_stale.py"),
                    "--root",
                    str(root),
                    "--model",
                    str(model),
                    "--strict",
                    "--format",
                    "text",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            after = doc.read_bytes()

        self.assertEqual(json_result.returncode, 1)
        self.assertEqual(text_result.returncode, 1)
        self.assertEqual(after, before)
        self.assertEqual(json_result.stderr, "")
        body = json.loads(json_result.stdout)
        self.assertEqual(body["findings"][0]["code"], "review-archive-destination")
        self.assertTrue(text_result.stdout.startswith("source_digest\t"))
        self.assertIn(
            f"\treview-archive-destination\tdoc.md\t{REVIEW_REPORTS_ARCHIVE}\t",
            text_result.stdout,
        )


if __name__ == "__main__":
    unittest.main()

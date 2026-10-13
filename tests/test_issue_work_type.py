from __future__ import annotations

import re
import unittest
from pathlib import Path


MODEL_ROOT = Path(__file__).resolve().parents[1] / "model"
TEMPLATE = MODEL_ROOT / "TEMPLATES" / "TEMPLATE.issue.common.md"
RULES = MODEL_ROOT / "RULES-ISSUE-DOCS.common.md"


def _frontmatter_keys(text: str) -> list[str]:
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "template has no frontmatter"
    return [line.split(":", 1)[0] for line in match.group(1).splitlines() if re.match(r"^[a-z_]+:", line)]


class IssueWorkTypeContractTests(unittest.TestCase):
    def test_template_declares_empty_work_type_after_status(self) -> None:
        text = TEMPLATE.read_text(encoding="utf-8")
        keys = _frontmatter_keys(text)

        self.assertIn("work_type", keys)
        self.assertEqual(keys.index("work_type"), keys.index("status") + 1)
        # Empty by default: the user answers it, nothing is inferred.
        self.assertRegex(text, r"(?m)^work_type:\s+#")

    def test_rules_document_work_type_values_and_ask_once(self) -> None:
        text = RULES.read_text(encoding="utf-8")

        self.assertIn("## Work type", text)
        section = text.split("## Work type", 1)[1].split("\n## ", 1)[0]
        self.assertIn("`sprint`", section)
        self.assertIn("`unplanned`", section)
        self.assertIn("Do not infer it from the tracker", section)
        # The creation step must point at the section, otherwise the field is never asked for.
        self.assertIn('(see "Work type")', text)


if __name__ == "__main__":
    unittest.main()

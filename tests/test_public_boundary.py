from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOTS = (ROOT / "skills", ROOT / "model", ROOT / "docs", ROOT / "examples")


class PublicBoundaryTests(unittest.TestCase):
    def test_public_tree_has_no_known_private_markers(self) -> None:
        private_markers = (
            "aff" + "irm",
            "crd" + "pltintl",
            "all-the-" + "things",
            "consumer-eng-" + "tools",
            "card platform " + "international",
            "card " + "simulator",
            "card-" + "simulator",
            "snow" + "flake",
            "chrono" + "sphere",
            "audit" + "board",
            "memory-" + "bank",
            "kt" + "lo",
            "proj-" + "368",
        )
        violations: list[str] = []
        for root in PUBLIC_ROOTS:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in {".md", ".json", ".toml", ".sh"}:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
                for marker in private_markers:
                    if marker in text:
                        violations.append(f"{path.relative_to(ROOT)}: {marker}")
        self.assertEqual(violations, [])

    def test_public_markdown_has_no_concrete_mcp_tool_namespaces(self) -> None:
        marker = "mcp" + "__"
        violations: list[str] = []
        for root in PUBLIC_ROOTS:
            if not root.exists():
                continue
            for path in root.rglob("*.md"):
                if marker in path.read_text(encoding="utf-8", errors="ignore"):
                    violations.append(str(path.relative_to(ROOT)))
        self.assertEqual(violations, [])

    def test_public_boyscout_does_not_preauthorize_provider_writes(self) -> None:
        skill = (ROOT / "skills" / "boyscout" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        frontmatter = skill.split("---", 2)[1]
        forbidden = (
            "mcp" + "__",
            "gh issue " + "create",
            "glab issue " + "create",
        )
        for marker in forbidden:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, frontmatter)


if __name__ == "__main__":
    unittest.main()

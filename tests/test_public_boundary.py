from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOTS = (ROOT / "skills", ROOT / "model", ROOT / "docs", ROOT / "examples")
PUBLIC_FILES = (ROOT / "README.md",)
PUBLIC_SUFFIXES = {".md", ".json", ".toml", ".sh", ".py", ".yaml", ".yml"}

sys.path.insert(0, str(ROOT / "skills" / "push-gate" / "scripts"))

from pre_push_audit import load_forbidden_values, resolve_values_file  # noqa: E402


class PublicBoundaryTests(unittest.TestCase):
    def test_public_tree_has_no_known_private_markers(self) -> None:
        values_file = resolve_values_file(ROOT, None)
        if values_file is None or not values_file.is_file():
            self.skipTest(
                "no forbidden-values file configured (git config pushgate.valuesFile)"
            )
        private_markers = tuple(
            value.lower() for value in load_forbidden_values(values_file)
        )
        violations: list[str] = []
        paths = list(PUBLIC_FILES)
        for root in PUBLIC_ROOTS:
            if root.exists():
                paths.extend(root.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix not in PUBLIC_SUFFIXES:
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

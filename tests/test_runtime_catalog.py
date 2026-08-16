from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "model" / "SCRIPTS"
sys.path.insert(0, str(SCRIPTS_DIR))

import runtime_catalog  # noqa: E402
import runtime_health  # noqa: E402
import runtime_manager  # noqa: E402
from _common import Reporter  # noqa: E402


class RuntimeCatalogTests(unittest.TestCase):
    def test_skill_destinations_match_runtime_contract(self) -> None:
        configs = runtime_catalog.RUNTIME_CONFIGS

        self.assertEqual(configs["claude"]["skills_dir"], Path("~/.claude/skills"))
        self.assertEqual(configs["opencode"]["skills_dir"], Path("~/.agents/skills"))
        self.assertEqual(configs["codex"]["skills_dir"], Path("~/.agents/skills"))
        self.assertEqual(
            configs["antigravity"]["skills_dir"],
            Path("~/.gemini/antigravity-cli/skills"),
        )
        self.assertNotIn("gemini", configs)

    def test_catalog_remains_compatible_with_existing_imports(self) -> None:
        self.assertIs(runtime_manager.RUNTIME_CONFIGS, runtime_catalog.RUNTIME_CONFIGS)
        self.assertIs(runtime_manager.RUNTIME_HOMES, runtime_catalog.RUNTIME_HOMES)
        self.assertIs(runtime_health.RUNTIME_CONFIGS, runtime_catalog.RUNTIME_CONFIGS)
        self.assertIs(runtime_health.RUNTIME_LABELS, runtime_catalog.RUNTIME_LABELS)

    def test_antigravity_is_a_skill_only_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            brain = root / "brain"
            repo = root / "repo"
            (home / ".gemini" / "antigravity-cli").mkdir(parents=True)
            (repo / "skills" / "brain").mkdir(parents=True)
            brain.mkdir()
            reporter = Reporter(root / "runtime-manager.log")

            with (
                patch.dict(os.environ, {"HOME": str(home)}),
                patch.object(runtime_manager, "resolve_repo_root", return_value=repo),
                redirect_stdout(StringIO()),
            ):
                runtime_manager.process_runtime(
                    "antigravity",
                    brain,
                    reporter,
                    dry_run=False,
                )

            link = home / ".gemini" / "antigravity-cli" / "skills" / "brain"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), (repo / "skills" / "brain").resolve())
            self.assertFalse((brain / "_AGENTS" / "ANTIGRAVITY").exists())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import io
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "model" / "SCRIPTS"
sys.path.insert(0, str(SCRIPTS_DIR))

from _common import Reporter  # noqa: E402
import runtime_manager  # noqa: E402


def tree_snapshot(root: Path) -> list[tuple[str, str, str]]:
    snapshot: list[tuple[str, str, str]] = []
    if not root.exists():
        return snapshot
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_symlink():
            snapshot.append((str(rel), "symlink", os.readlink(path)))
        elif path.is_file():
            snapshot.append((str(rel), "file", path.read_text(encoding="utf-8")))
        elif path.is_dir():
            snapshot.append((str(rel), "dir", ""))
    return snapshot


class RuntimeManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.brain = self.root / "brain"
        self.repo = self.root / "repo"
        self.home.mkdir()
        self.brain.mkdir()
        (self.repo / "skills" / "brain").mkdir(parents=True)
        self.reporter = Reporter(self.root / "runtime-manager.log")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def process_runtime(self, runtime: str, *, dry_run: bool = False) -> None:
        with (
            patch.dict(os.environ, {"HOME": str(self.home)}),
            patch.object(runtime_manager, "resolve_repo_root", return_value=self.repo),
            redirect_stdout(io.StringIO()),
        ):
            runtime_manager.process_runtime(
                runtime,
                self.brain,
                self.reporter,
                dry_run=dry_run,
            )

    def process_codex(self, *, dry_run: bool = False) -> None:
        self.process_runtime("codex", dry_run=dry_run)

    def test_dry_run_reports_direction_a_without_mutating(self) -> None:
        local_config = self.home / ".codex" / "config.toml"
        local_config.parent.mkdir(parents=True)
        local_config.write_text("model = 'local'\n", encoding="utf-8")
        before_brain = tree_snapshot(self.brain)
        before_home = tree_snapshot(self.home)

        self.process_codex(dry_run=True)

        self.assertEqual(tree_snapshot(self.brain), before_brain)
        self.assertEqual(tree_snapshot(self.home), before_home)
        self.assertTrue(local_config.is_file())

    def test_direction_a_ingests_local_config_and_is_idempotent(self) -> None:
        local_config = self.home / ".codex" / "config.toml"
        local_config.parent.mkdir(parents=True)
        local_config.write_text("model = 'local'\n", encoding="utf-8")
        unrelated = self.home / ".claude" / "settings.json"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text('{"theme":"dark"}\n', encoding="utf-8")

        self.process_codex()
        brain_config = self.brain / "_AGENTS" / "CODEX" / "config.toml"
        first_brain = tree_snapshot(self.brain)
        first_home = tree_snapshot(self.home)
        self.process_codex()
        second_brain = tree_snapshot(self.brain)
        second_home = tree_snapshot(self.home)

        self.assertEqual(first_brain, second_brain)
        self.assertEqual(first_home, second_home)
        self.assertEqual(brain_config.read_text(), "model = 'local'\n")
        self.assertEqual(stat.S_IMODE(brain_config.stat().st_mode), 0o600)
        self.assertTrue(local_config.is_symlink())
        self.assertEqual(local_config.resolve(), brain_config.resolve())
        self.assertEqual(unrelated.read_text(), '{"theme":"dark"}\n')
        self.assertFalse(list((self.home / ".codex").glob("*.backup-*")))

    def test_direction_b_implants_brain_config(self) -> None:
        brain_config = self.brain / "_AGENTS" / "CODEX" / "config.toml"
        brain_config.parent.mkdir(parents=True)
        brain_config.write_text("model = 'brain'\n", encoding="utf-8")

        self.process_codex()
        local_config = self.home / ".codex" / "config.toml"

        self.assertTrue(local_config.is_symlink())
        self.assertEqual(local_config.resolve(), brain_config.resolve())
        self.assertEqual(stat.S_IMODE(brain_config.stat().st_mode), 0o600)

    def test_conflict_quarantines_local_and_brain_wins(self) -> None:
        brain_config = self.brain / "_AGENTS" / "CODEX" / "config.toml"
        brain_config.parent.mkdir(parents=True)
        brain_config.write_text("model = 'brain'\n", encoding="utf-8")
        local_config = self.home / ".codex" / "config.toml"
        local_config.parent.mkdir(parents=True)
        local_config.write_text("model = 'local'\n", encoding="utf-8")

        self.process_codex()
        quarantine = self.brain / "INBOX" / "_RUNTIME" / "CODEX" / "config.toml"
        first_brain = tree_snapshot(self.brain)
        first_home = tree_snapshot(self.home)
        self.process_codex()

        self.assertEqual(tree_snapshot(self.brain), first_brain)
        self.assertEqual(tree_snapshot(self.home), first_home)
        self.assertEqual(quarantine.read_text(), "model = 'local'\n")
        self.assertTrue(local_config.is_symlink())
        self.assertEqual(local_config.resolve(), brain_config.resolve())
        self.assertEqual(brain_config.read_text(), "model = 'brain'\n")

    def test_directory_mapping_is_ingested_and_linked(self) -> None:
        local_memory = self.home / ".claude" / "memory"
        local_memory.mkdir(parents=True)
        (local_memory / "MEMORY.md").write_text("# private memory\n", encoding="utf-8")

        self.process_runtime("claude")
        brain_memory = self.brain / "_AGENTS" / "CLAUDE" / "memory"
        first_brain = tree_snapshot(self.brain)
        first_home = tree_snapshot(self.home)
        self.process_runtime("claude")

        self.assertEqual(tree_snapshot(self.brain), first_brain)
        self.assertEqual(tree_snapshot(self.home), first_home)
        self.assertTrue(local_memory.is_symlink())
        self.assertEqual(local_memory.resolve(), brain_memory.resolve())
        self.assertEqual(
            (brain_memory / "MEMORY.md").read_text(encoding="utf-8"),
            "# private memory\n",
        )


if __name__ == "__main__":
    unittest.main()

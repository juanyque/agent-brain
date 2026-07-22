from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "model" / "SCRIPTS" / "skill_link.sh"


class SkillLinkTests(unittest.TestCase):
    def run_link(
        self, source: Path, home: Path, *args: str
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOME"] = str(home)
        return subprocess.run(
            ["bash", str(SCRIPT), str(source), *args],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_external_skill_dry_run_apply_and_repeat_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            source = root / "project" / "skills" / "confold"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: confold\n---\n", encoding="utf-8")
            runtime_homes = [
                home / ".agents",
                home / ".claude",
                home / ".codex",
                home / ".config" / "opencode",
            ]
            for runtime_home in runtime_homes:
                runtime_home.mkdir(parents=True)

            dry_run = self.run_link(source, home)
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            self.assertEqual(dry_run.stdout.count("  LINK    "), len(runtime_homes))
            for runtime_home in runtime_homes:
                self.assertFalse((runtime_home / "skills" / "confold").is_symlink())

            applied = self.run_link(source, home, "--apply")
            self.assertEqual(applied.returncode, 0, applied.stderr)
            for runtime_home in runtime_homes:
                link = runtime_home / "skills" / "confold"
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), source.resolve())

            repeated = self.run_link(source, home, "--apply")
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(repeated.stdout.count("  OK      "), len(runtime_homes))
            self.assertFalse(list(home.rglob("confold.backup-*")))

    def test_external_skill_requires_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "broken-skill"
            source.mkdir()
            result = self.run_link(source, root / "home")
            self.assertEqual(result.returncode, 2)
            self.assertIn("skill source has no SKILL.md", result.stderr)

    def test_agent_brain_skill_name_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            runtime_home = home / ".agents"
            runtime_home.mkdir(parents=True)

            result = self.run_link(Path("boyscout"), home, str(runtime_home), "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)
            link = runtime_home / "skills" / "boyscout"
            self.assertTrue(link.is_symlink())
            self.assertEqual(
                link.resolve(),
                (SCRIPT.parents[2] / "skills" / "boyscout").resolve(),
            )


if __name__ == "__main__":
    unittest.main()

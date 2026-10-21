from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "model" / "SCRIPTS" / "skill_link.sh"


class SkillLinkTests(unittest.TestCase):
    def run_link(
        self, source: Path, home: Path, *args: str
    ) -> subprocess.CompletedProcess[str]:
        home.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["SKILL_LINK_LOG_FILE"] = str(home / "skill_link.log")
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
            detected_homes = [
                home / ".agents",
                home / ".claude",
                home / ".codex",
                home / ".config" / "opencode",
                home / ".gemini" / "antigravity-cli",
            ]
            for runtime_home in detected_homes:
                runtime_home.mkdir(parents=True)
            target_homes = [
                home / ".agents",
                home / ".claude",
                home / ".gemini" / "antigravity-cli",
            ]

            dry_run = self.run_link(source, home)
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            self.assertEqual(dry_run.stdout.count("  LINK    "), len(target_homes))
            for runtime_home in target_homes:
                self.assertFalse((runtime_home / "skills" / "confold").is_symlink())

            applied = self.run_link(source, home, "--apply")
            self.assertEqual(applied.returncode, 0, applied.stderr)
            for runtime_home in target_homes:
                link = runtime_home / "skills" / "confold"
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), source.resolve())
            self.assertFalse((home / ".codex" / "skills" / "confold").is_symlink())
            self.assertFalse(
                (home / ".config" / "opencode" / "skills" / "confold").is_symlink()
            )
            self.assertFalse((home / ".gemini" / "skills" / "confold").is_symlink())

            repeated = self.run_link(source, home, "--apply")
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(repeated.stdout.count("  OK      "), len(target_homes))
            self.assertFalse(list(home.rglob("confold.backup-*")))

    def test_external_skill_requires_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "broken-skill"
            source.mkdir()
            result = self.run_link(source, root / "home")
            self.assertEqual(result.returncode, 2)
            self.assertIn("skill source has no SKILL.md", result.stderr)

    def test_apply_writes_latest_log_without_hiding_console_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            script = root / "agent-brain" / "model" / "SCRIPTS" / "skill_link.sh"
            script.parent.mkdir(parents=True)
            shutil.copy2(SCRIPT, script)
            source = root / "project" / "skills" / "confold"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: confold\n---\n", encoding="utf-8")
            home = root / "home"
            runtime_home = home / ".agents"
            runtime_home.mkdir(parents=True)

            result = subprocess.run(
                ["bash", str(script), str(source), str(runtime_home), "--apply"],
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "HOME": str(home)},
            )
            log_path = script.with_suffix(".log")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("mode:   apply", result.stdout)
            self.assertTrue(log_path.is_file())
            self.assertEqual(log_path.read_text(encoding="utf-8"), result.stdout)

    def test_as_links_a_suffixed_source_under_a_clean_name_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            source = root / "consumer-tools" / "team-memory_jane.doe"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: team-memory\n---\n", encoding="utf-8")
            runtime = home / ".claude"
            runtime.mkdir(parents=True)

            dry_run = self.run_link(source, home, str(runtime), "--as", "team-memory")
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            self.assertIn("skill_link: team-memory", dry_run.stdout)
            self.assertFalse((runtime / "skills" / "team-memory").exists())

            applied = self.run_link(source, home, str(runtime), "--as=team-memory", "--apply")
            self.assertEqual(applied.returncode, 0, applied.stderr)
            link = runtime / "skills" / "team-memory"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), source.resolve())
            self.assertFalse((runtime / "skills" / "team-memory_jane.doe").exists())

            repeated = self.run_link(source, home, str(runtime), "--as", "team-memory", "--apply")
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertIn("  OK      ", repeated.stdout)
            self.assertEqual(list((runtime / "skills").glob("*.backup-*")), [])

    def test_as_replaces_a_wrongly_named_link_only_through_the_backup_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            source = root / "tools" / "memo_jane"
            other = root / "tools" / "elsewhere"
            for directory in (source, other):
                directory.mkdir(parents=True)
                (directory / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
            runtime = home / ".agents"
            (runtime / "skills").mkdir(parents=True)
            (runtime / "skills" / "memo").symlink_to(other)

            result = self.run_link(source, home, str(runtime), "--as", "memo", "--apply")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((runtime / "skills" / "memo").resolve(), source.resolve())
            backups = list((runtime / "skills").glob("memo.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].resolve(), other.resolve())

    def test_as_rejects_invalid_names_and_a_missing_value(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            source = root / "skills" / "demo"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
            runtime = home / ".claude"
            runtime.mkdir(parents=True)

            for bad in ("../escape", "a/b", ".hidden", "-lead", "has space", ""):
                with self.subTest(name=bad):
                    result = self.run_link(source, home, str(runtime), "--as", bad, "--apply")
                    self.assertEqual(result.returncode, 2, result.stdout)
                    self.assertIn("invalid --as link name", result.stderr)
            self.assertFalse((runtime / "skills").exists())

            missing = self.run_link(source, home, str(runtime), "--as")
            self.assertEqual(missing.returncode, 2)
            self.assertIn("--as requires a link name", missing.stderr)

    def test_as_also_works_with_an_agent_brain_skill_name(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw) / "home"
            runtime = home / ".agents"
            runtime.mkdir(parents=True)
            repo_skill = SCRIPT.parents[2] / "skills" / "boyscout"

            result = subprocess.run(
                ["bash", str(SCRIPT), "boyscout", str(runtime), "--as", "scout", "--apply"],
                check=False, capture_output=True, text=True,
                env={**os.environ, "HOME": str(home), "SKILL_LINK_LOG_FILE": str(home / "skill_link.log")},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((runtime / "skills" / "scout").resolve(), repo_skill.resolve())
            self.assertFalse((runtime / "skills" / "boyscout").exists())

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

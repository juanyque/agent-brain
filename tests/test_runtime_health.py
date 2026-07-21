from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "model" / "SCRIPTS"
sys.path.insert(0, str(SCRIPTS_DIR))

from runtime_health import HealthCheck, RUNTIME_CONFIGS, check_runtime  # noqa: E402


class RuntimeHealthTests(unittest.TestCase):
    def test_all_supported_runtime_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            home = root / "home"
            repo = root / "repo"
            skill = repo / "skills" / "brain"
            skill.mkdir(parents=True)

            for name, config in RUNTIME_CONFIGS.items():
                brain_dir = brain / "_AGENTS" / config["agents_subdir"]
                local_raw = str(config["local_dir"])
                local_dir = home / local_raw[2:]
                for source_name, target_name in config["mappings"]:
                    source = brain_dir / source_name
                    source.parent.mkdir(parents=True, exist_ok=True)
                    if source_name == "memory":
                        source.mkdir()
                    else:
                        source.touch()
                    if target_name in config.get("private_targets", set()):
                        source.chmod(0o600)
                    target = local_dir / target_name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.symlink_to(source)

                skills_raw = str(config.get("skills_dir", config["local_dir"] / "skills"))
                skills_dir = home / skills_raw[2:]
                skills_dir.mkdir(parents=True, exist_ok=True)
                skill_link = skills_dir / "brain"
                if not skill_link.exists() and not skill_link.is_symlink():
                    skill_link.symlink_to(skill)

            shared_memory = brain / "_AGENTS" / "SHARED" / "memory"
            shared_memory.mkdir(parents=True)
            shared_link = home / ".agents" / "brain-memory"
            shared_link.parent.mkdir(parents=True, exist_ok=True)
            shared_link.symlink_to(shared_memory)

            check = HealthCheck()
            for name in RUNTIME_CONFIGS:
                with self.subTest(runtime=name):
                    check_runtime(
                        name,
                        brain,
                        check,
                        home_root=home,
                        repo_root=repo,
                    )
            self.assertFalse(check.failed)
            codex_config = brain / "_AGENTS" / "CODEX" / "config.toml"
            self.assertEqual(stat.S_IMODE(codex_config.stat().st_mode), 0o600)

    def test_wrong_runtime_link_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            home = root / "home"
            repo = root / "repo"
            source = brain / "_AGENTS" / "CLAUDE" / "settings.json"
            source.parent.mkdir(parents=True)
            source.touch()
            wrong = root / "wrong-settings.json"
            wrong.touch()
            local = home / ".claude" / "settings.json"
            local.parent.mkdir(parents=True)
            local.symlink_to(wrong)
            skill = repo / "skills" / "brain"
            skill.mkdir(parents=True)
            skills_dir = home / ".claude" / "skills"
            skills_dir.mkdir(parents=True)
            (skills_dir / "brain").symlink_to(skill)

            check = HealthCheck()
            check_runtime(
                "claude",
                brain,
                check,
                home_root=home,
                repo_root=repo,
            )
            self.assertTrue(check.failed)

    def test_inactive_runtime_is_not_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            check = HealthCheck()
            check_runtime(
                "opencode",
                root / "brain",
                check,
                home_root=root / "home",
                repo_root=root / "repo",
            )
            self.assertFalse(check.failed)


if __name__ == "__main__":
    unittest.main()

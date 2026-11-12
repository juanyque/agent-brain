from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BRAIN_DEFAULT = REPO_ROOT / "skills" / "brain" / "scripts" / "brain_default.py"
MODEL_ROOT = REPO_ROOT / "model"


class BrainDefaultCliTests(unittest.TestCase):
    def run_cli(self, home: Path, *args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        env = os.environ.copy()
        env.pop("XDG_CONFIG_HOME", None)
        env["HOME"] = str(home)
        result = subprocess.run(
            [sys.executable, str(BRAIN_DEFAULT), *args],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        return result, json.loads(result.stdout)

    @staticmethod
    def attach(brain: Path, model: Path = MODEL_ROOT) -> None:
        brain.mkdir(parents=True, exist_ok=True)
        (brain / "_COMMON").symlink_to(model, target_is_directory=True)

    def test_get_is_unset_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result, payload = self.run_cli(Path(raw), "get")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["status"], "unset")

    def test_set_without_apply_is_a_dry_run_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home, brain = Path(raw) / "home", Path(raw) / "brain"
            home.mkdir()
            self.attach(brain)

            result, payload = self.run_cli(home, "set", "--brain-root", str(brain))

            self.assertEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "dry-run")
            self.assertFalse((home / ".config" / "agent-brain" / "default_brain.json").exists())

    def test_set_apply_then_get_round_trips_with_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home, brain = Path(raw) / "home", Path(raw) / "brain"
            home.mkdir()
            self.attach(brain)

            set_result, _ = self.run_cli(home, "set", "--brain-root", str(brain), "--apply")
            get_result, get_payload = self.run_cli(home, "get")
            config = home / ".config" / "agent-brain" / "default_brain.json"
            mode = stat.S_IMODE(config.stat().st_mode)
            leftovers = [p.name for p in config.parent.iterdir() if p.name != "default_brain.json"]

        self.assertEqual(set_result.returncode, 0)
        self.assertEqual(get_result.returncode, 0)
        self.assertEqual((get_payload["status"], get_payload["brain"]), ("ok", str(brain.resolve())))
        self.assertEqual(mode, 0o600)
        self.assertEqual(leftovers, [])

    def test_set_refuses_non_brains_and_wrong_model_brains(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home, plain, legacy, old = Path(raw) / "home", Path(raw) / "plain", Path(raw) / "legacy", Path(raw) / "old"
            home.mkdir()
            plain.mkdir()
            old.mkdir()
            self.attach(legacy, old)
            for target in (plain, legacy, Path(raw) / "missing"):
                with self.subTest(target=target.name):
                    result, payload = self.run_cli(home, "set", "--brain-root", str(target), "--apply")
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(payload["status"], "refused")
            self.assertFalse((home / ".config").exists())

    def test_get_reports_a_removed_brain_as_invalid_without_touching_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home, brain = Path(raw) / "home", Path(raw) / "brain"
            home.mkdir()
            self.attach(brain)
            self.run_cli(home, "set", "--brain-root", str(brain), "--apply")
            (brain / "_COMMON").unlink()
            brain.rmdir()

            result, payload = self.run_cli(home, "get")
            still_there = (home / ".config" / "agent-brain" / "default_brain.json").exists()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["status"], "invalid")
        self.assertTrue(still_there)

    def test_clear_is_dry_run_until_apply(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home, brain = Path(raw) / "home", Path(raw) / "brain"
            home.mkdir()
            self.attach(brain)
            self.run_cli(home, "set", "--brain-root", str(brain), "--apply")

            _, dry = self.run_cli(home, "clear")
            still_set, _ = self.run_cli(home, "get")
            _, applied = self.run_cli(home, "clear", "--apply")
            now_unset, _ = self.run_cli(home, "get")

        self.assertEqual((dry["status"], dry["would_remove"]), ("dry-run", True))
        self.assertEqual(still_set.returncode, 0)
        self.assertEqual(applied["status"], "cleared")
        self.assertEqual(now_unset.returncode, 1)

    def test_xdg_config_home_is_honoured_when_absolute(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home, xdg, brain = Path(raw) / "home", Path(raw) / "xdg", Path(raw) / "brain"
            home.mkdir()
            self.attach(brain)
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["XDG_CONFIG_HOME"] = str(xdg)
            subprocess.run(
                [sys.executable, str(BRAIN_DEFAULT), "set", "--brain-root", str(brain), "--apply"],
                env=env, check=True, capture_output=True, text=True,
            )

            self.assertTrue((xdg / "agent-brain" / "default_brain.json").is_file())
            self.assertFalse((home / ".config").exists())


if __name__ == "__main__":
    unittest.main()

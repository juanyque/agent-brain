from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_bootstrap import run_pty_bootstrap


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_BOOTSTRAP = REPO_ROOT / "bootstrap-zero.sh"
INTERNAL_BOOTSTRAP = REPO_ROOT / "model" / "SCRIPTS" / "bootstrap-zero.sh"
ANSI_ESCAPE = "\x1b["


def bootstrap_environment(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("NO_COLOR", None)
    return env


class BootstrapColorTests(unittest.TestCase):
    def test_redirected_output_has_no_ansi_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            home = root / "home"
            brain.mkdir()
            home.mkdir()

            result = subprocess.run(
                ["bash", str(INTERNAL_BOOTSTRAP), "--brain", str(brain)],
                cwd=REPO_ROOT,
                env=bootstrap_environment(home),
                text=True,
                capture_output=True,
                check=False,
                timeout=20,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(ANSI_ESCAPE, result.stdout + result.stderr)

    def test_terminal_output_colors_commands_sections_and_user_command(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            home = root / "home"
            brain.mkdir()
            home.mkdir()

            returncode, output, _ = run_pty_bootstrap(
                ["bash", str(INTERNAL_BOOTSTRAP), "--brain", str(brain)],
                bootstrap_environment(home),
                input_bytes=None,
                stdin_devnull=False,
                timeout=20,
            )

        self.assertEqual(returncode, 0, output)
        self.assertIn("\x1b[34m== git-snapshot ==", output)
        self.assertIn("\x1b[33mCOMMAND:", output)
        self.assertIn("\x1b[36mcurl -fsSL", output)

    def test_no_color_disables_ansi_sequences_in_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            home = root / "home"
            brain.mkdir()
            home.mkdir()
            env = bootstrap_environment(home)
            env["NO_COLOR"] = "1"

            returncode, output, _ = run_pty_bootstrap(
                ["bash", str(INTERNAL_BOOTSTRAP), "--brain", str(brain)],
                env,
                input_bytes=None,
                stdin_devnull=False,
                timeout=20,
            )

        self.assertEqual(returncode, 0, output)
        self.assertNotIn(ANSI_ESCAPE, output)

    def test_colored_terminal_output_keeps_persistent_logs_plain(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            home = root / "home"
            log_dir = root / "logs"
            brain.mkdir()
            home.mkdir()
            env = bootstrap_environment(home)
            env["AGENT_BRAIN_LOG_DIR"] = str(log_dir)

            returncode, output, _ = run_pty_bootstrap(
                ["bash", str(INTERNAL_BOOTSTRAP), "--brain", str(brain)],
                env,
                input_bytes=None,
                stdin_devnull=False,
                timeout=20,
            )
            logs = list(log_dir.glob("*.log"))
            log_contents = "".join(path.read_text(encoding="utf-8") for path in logs)

        self.assertEqual(returncode, 0, output)
        self.assertIn(ANSI_ESCAPE, output)
        self.assertTrue(logs)
        self.assertNotIn(ANSI_ESCAPE, log_contents)

    def test_public_entrypoint_colors_commands_and_warning_in_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            checkout = root / "agent-brain"
            internal = checkout / "model" / "SCRIPTS" / "bootstrap-zero.sh"
            home = root / "home"
            (checkout / ".git").mkdir(parents=True)
            internal.parent.mkdir(parents=True)
            internal.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            home.mkdir()
            env = bootstrap_environment(home)
            env["AGENT_BRAIN_HOME"] = str(checkout)

            returncode, output, _ = run_pty_bootstrap(
                ["bash", str(PUBLIC_BOOTSTRAP)],
                env,
                input_bytes=None,
                stdin_devnull=False,
                timeout=20,
            )

        self.assertEqual(returncode, 0, output)
        self.assertIn("\x1b[33mCOMMAND:", output)
        self.assertIn("\x1b[38;5;208m", output)


if __name__ == "__main__":
    unittest.main()

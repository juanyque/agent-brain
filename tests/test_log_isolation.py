from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "model" / "SCRIPTS" / "bootstrap-zero.sh"
PRODUCT_LOGS = (
    ROOT / "model" / "SCRIPTS" / "home_setup.log",
    ROOT / "model" / "SCRIPTS" / "runtime_manager.log",
)


def product_log_snapshot() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in PRODUCT_LOGS
    }


class BootstrapLogIsolationTests(unittest.TestCase):
    def test_bootstrap_writes_delegated_logs_outside_product_tree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            brain = base / "brain"
            home = base / "home"
            brain.mkdir()
            home.mkdir()
            (brain / "seed.md").write_text("seed\n", encoding="utf-8")
            env = os.environ.copy()
            env.pop("AGENT_BRAIN_LOG_DIR", None)
            env.update(
                {
                    "HOME": str(home),
                    "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_CONFIG_SYSTEM": "/dev/null",
                    "GIT_EDITOR": "false",
                    "GIT_TERMINAL_PROMPT": "0",
                }
            )
            before = product_log_snapshot()

            result = subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "--brain",
                    str(brain),
                    "--runtime",
                    "codex",
                    "--apply",
                ],
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                text=True,
                capture_output=True,
                check=False,
                timeout=20,
            )
            after = product_log_snapshot()
            log_line = next(
                line for line in result.stdout.splitlines() if line.startswith("  logs: ")
            )
            log_dir = Path(log_line.removeprefix("  logs: "))
            home_setup_log_exists = (log_dir / "home_setup.log").is_file()
            runtime_manager_log_exists = (log_dir / "runtime_manager.log").is_file()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(after, before)
        self.assertTrue(home_setup_log_exists)
        self.assertTrue(runtime_manager_log_exists)


if __name__ == "__main__":
    unittest.main()

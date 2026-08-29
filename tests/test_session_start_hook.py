from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "model" / "SCRIPTS" / "session_start_hook.py"
MODEL_ROOT = REPO_ROOT / "model"


def attach(brain: Path, model: Path = MODEL_ROOT) -> None:
    brain.mkdir(parents=True, exist_ok=True)
    (brain / "_COMMON").symlink_to(model, target_is_directory=True)


def run_hook(runtime: str, stdin_payload: dict, agent_brain_home: Path) -> subprocess.CompletedProcess[str]:
    import os

    env = os.environ.copy()
    env["AGENT_BRAIN_HOME"] = str(agent_brain_home)
    return subprocess.run(
        [sys.executable, str(HOOK), "--runtime", runtime],
        input=json.dumps(stdin_payload),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


class SessionStartHookTests(unittest.TestCase):
    def test_injects_reminder_when_cwd_is_inside_a_brain(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "myvault"
            attach(brain)
            sub_cwd = brain / "WIP"
            sub_cwd.mkdir()

            result = run_hook("claude", {"cwd": str(sub_cwd)}, agent_brain_home=REPO_ROOT)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("myvault", context)
        self.assertIn("invoke the `brain` skill", context)

    def test_codex_reminder_uses_the_explicit_invocation_phrase(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "othervault"
            attach(brain)

            result = run_hook("codex", {"cwd": str(brain)}, agent_brain_home=REPO_ROOT)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("$brain nueva sesion en español", context)

    def test_emits_empty_object_when_cwd_is_not_inside_a_brain(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            unrelated = Path(raw) / "not-a-brain"
            unrelated.mkdir()

            result = run_hook("claude", {"cwd": str(unrelated)}, agent_brain_home=REPO_ROOT)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})

    def test_falls_back_to_pwd_env_when_cwd_field_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "pwdvault"
            attach(brain)
            import os

            env = os.environ.copy()
            env["AGENT_BRAIN_HOME"] = str(REPO_ROOT)
            env["PWD"] = str(brain)
            result = subprocess.run(
                [sys.executable, str(HOOK), "--runtime", "claude"],
                input=json.dumps({}),
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("pwdvault", payload["hookSpecificOutput"]["additionalContext"])

    def test_emits_empty_object_on_malformed_stdin(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HOOK), "--runtime", "claude"],
            input="not json{{{",
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})

    def test_emits_empty_object_when_agent_brain_home_is_wrong(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "somevault"
            attach(brain)

            result = run_hook("claude", {"cwd": str(brain)}, agent_brain_home=Path(raw) / "nonexistent-agent-brain")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})

    def test_unknown_runtime_is_rejected_by_argparse(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HOOK), "--runtime", "opencode"],
            input="{}",
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()

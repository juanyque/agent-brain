from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "model" / "SCRIPTS" / "session_start_hook.py"
MODEL_ROOT = REPO_ROOT / "model"

sys.path.insert(0, str(HOOK.parent))
import session_start_hook  # noqa: E402


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

    def test_fails_closed_on_malformed_stdin_even_when_pwd_is_inside_a_brain(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "malformedvault"
            attach(brain)
            import os

            env = os.environ.copy()
            env["AGENT_BRAIN_HOME"] = str(REPO_ROOT)
            env["PWD"] = str(brain)
            result = subprocess.run(
                [sys.executable, str(HOOK), "--runtime", "claude"],
                input="not json{{{",
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {},
            "malformed stdin must fail closed immediately, not fall back to PWD",
        )

    def test_fails_closed_on_non_object_json_even_when_pwd_is_inside_a_brain(self) -> None:
        # `[]`, `null`, and a bare scalar are all syntactically valid JSON,
        # so they slip past the json.loads() try/except -- resolve_cwd()
        # then has to reject them itself, or PWD's real brain leaks through.
        for payload in ("[]", "null", '"scalar"'):
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as raw:
                    brain = Path(raw) / "wrongshapevault"
                    attach(brain)
                    import os

                    env = os.environ.copy()
                    env["AGENT_BRAIN_HOME"] = str(REPO_ROOT)
                    env["PWD"] = str(brain)
                    result = subprocess.run(
                        [sys.executable, str(HOOK), "--runtime", "claude"],
                        input=payload,
                        text=True,
                        capture_output=True,
                        check=False,
                        env=env,
                    )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {})

    def test_discovers_brain_without_agent_brain_home_env_var(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "selflocatedvault"
            attach(brain)
            fake_home = Path(raw) / "fake-home"
            fake_home.mkdir()
            import os

            env = os.environ.copy()
            env.pop("AGENT_BRAIN_HOME", None)
            # A HOME with no ~/.local/share/agent-brain makes the historical
            # (pre-fix) Path.home()-based default fail to find anything --
            # this is what actually proves discovery now comes from the
            # script's own __file__ location, not a coincidence of this
            # machine's real checkout living at the historical default path.
            env["HOME"] = str(fake_home)
            result = subprocess.run(
                [sys.executable, str(HOOK), "--runtime", "claude"],
                input=json.dumps({"cwd": str(brain)}),
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("selflocatedvault", payload["hookSpecificOutput"]["additionalContext"])

    def test_resolve_agent_brain_home_defaults_to_the_scripts_own_checkout(self) -> None:
        import os

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                session_start_hook,
                "__file__",
                "/fake/checkout/model/SCRIPTS/session_start_hook.py",
            ),
        ):
            result = session_start_hook.resolve_agent_brain_home()

        self.assertEqual(result, Path("/fake/checkout"))

    def test_emits_empty_object_when_agent_brain_home_is_wrong(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "somevault"
            attach(brain)

            result = run_hook("claude", {"cwd": str(brain)}, agent_brain_home=Path(raw) / "nonexistent-agent-brain")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})

    def test_unrecognized_runtime_argument_fails_closed_instead_of_crashing(self) -> None:
        # A misconfigured hook entry (unsupported --runtime value, or the flag
        # itself misspelled) must not break session start any more than a
        # missing brain does -- argparse's own SystemExit is a fail-safe case
        # too, not just runtime-discovery errors.
        for bad_args in (["--runtime", "opencode"], ["--runtime"], []):
            with self.subTest(bad_args=bad_args):
                result = subprocess.run(
                    [sys.executable, str(HOOK), *bad_args],
                    input="{}",
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {})


if __name__ == "__main__":
    unittest.main()

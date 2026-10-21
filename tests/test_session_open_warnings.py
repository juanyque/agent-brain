from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tests.support.session_open_test_support import SCRIPTS_DIR, attach_current_model

sys.path.insert(0, str(SCRIPTS_DIR))

from session_digest import (  # noqa: E402
    SessionDigestState,
    fixed_session_digest_request,
    render_session_digest,
)
from session_open_context import collect_session_digest_state  # noqa: E402
from session_open_warnings import session_request_warnings  # noqa: E402

MARKERS = ("CODEX_SESSION_ID", "CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "OPENCODE_SESSION_ID")


def warn(runtime: str = "codex", cwd: str = "", process_cwd="/work", environ=None, explicit=True):
    return session_request_warnings(
        runtime, cwd, runtime_explicit=explicit, process_cwd=process_cwd, environ=environ or {}
    )


class CwdWarningTests(unittest.TestCase):
    def test_equivalent_paths_are_silent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            real = Path(raw).resolve() / "project"
            real.mkdir()
            link = Path(raw) / "link"
            link.symlink_to(real, target_is_directory=True)
            for cwd in (str(real), str(link), f"{real}/../project", f"{real}/"):
                with self.subTest(cwd):
                    self.assertEqual(warn(cwd=cwd, process_cwd=str(real)), ())
            self.assertEqual(warn(cwd=".", process_cwd=str(real)), ())

    def test_a_different_cwd_warns_once_and_says_it_may_be_intentional(self) -> None:
        result = warn(cwd="/elsewhere", process_cwd="/work")
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].startswith("cwd-mismatch:"))
        self.assertIn("may be intentional", result[0])

    def test_omitted_cwd_or_unknown_process_cwd_is_silent(self) -> None:
        self.assertEqual(warn(cwd=""), ())
        self.assertEqual(warn(cwd="   "), ())
        self.assertEqual(warn(cwd="/elsewhere", process_cwd=None), ())

    def test_failed_resolution_is_not_fatal(self) -> None:
        self.assertEqual(warn(cwd="bad\0path", process_cwd="/work"), ())


class RuntimeWarningTests(unittest.TestCase):
    def test_each_family_mismatch_names_markers_not_values(self) -> None:
        cases = (
            ("claude", {"CODEX_SESSION_ID": "secret-1"}, "codex", "CODEX_SESSION_ID"),
            ("codex", {"CLAUDE_CODE_SESSION_ID": "secret-2"}, "claude", "CLAUDE_CODE_SESSION_ID"),
            ("opencode", {"CODEX_THREAD_ID": "secret-3"}, "codex", "CODEX_THREAD_ID"),
            ("codex", {"OPENCODE_SESSION_ID": "secret-4"}, "opencode", "OPENCODE_SESSION_ID"),
        )
        for runtime, environ, family, marker in cases:
            with self.subTest(runtime=runtime, marker=marker):
                result = warn(runtime=runtime, environ=environ)
                self.assertEqual(len(result), 1)
                self.assertTrue(result[0].startswith("runtime-env-mismatch:"))
                self.assertIn(family, result[0])
                self.assertIn(marker, result[0])
                self.assertNotIn("secret", result[0])

    def test_matching_generic_and_blank_markers_are_silent(self) -> None:
        self.assertEqual(warn("codex", environ={"CODEX_SESSION_ID": "x"}), ())
        self.assertEqual(warn("claude", environ={"CLAUDE_CODE_SESSION_ID": "x"}), ())
        self.assertEqual(warn("generic", environ={"CODEX_SESSION_ID": "x"}), ())
        self.assertEqual(warn("claude", environ={"CODEX_SESSION_ID": "  ", "CODEX_THREAD_ID": ""}), ())
        self.assertEqual(warn("claude", environ={}), ())

    def test_same_family_markers_do_not_duplicate_or_conflict(self) -> None:
        both = {"CODEX_SESSION_ID": "a", "CODEX_THREAD_ID": "b"}
        self.assertEqual(warn("codex", environ=both), ())
        result = warn("claude", environ=both)
        self.assertEqual(len(result), 1)
        self.assertIn("CODEX_SESSION_ID", result[0])
        self.assertIn("CODEX_THREAD_ID", result[0])

    def test_several_families_give_one_ambiguity_warning_whatever_the_provenance(self) -> None:
        environ = {"CODEX_SESSION_ID": "a", "CLAUDE_CODE_SESSION_ID": "b"}
        for explicit in (True, False):
            with self.subTest(explicit=explicit):
                result = warn("claude", environ=environ, explicit=explicit)
                self.assertEqual(len(result), 1)
                self.assertTrue(result[0].startswith("runtime-env-ambiguous:"))

    def test_inferred_runtime_never_gets_a_mismatch_warning(self) -> None:
        self.assertEqual(warn("generic", environ={"CODEX_SESSION_ID": "a"}, explicit=False), ())
        self.assertEqual(warn("codex", environ={"CLAUDE_CODE_SESSION_ID": "a"}, explicit=False), ())


class DigestWarningTests(unittest.TestCase):
    def test_fixture_collection_ignores_request_warnings(self) -> None:
        request = fixed_session_digest_request()
        state = collect_session_digest_state(request)
        self.assertEqual(state.request_warnings, ())
        self.assertNotIn("request_warnings", render_session_digest(state))

    def test_warnings_render_as_their_own_block_only_when_present(self) -> None:
        state = collect_session_digest_state(fixed_session_digest_request())
        shown = render_session_digest(
            SessionDigestState(**{**{f: getattr(state, f) for f in state.__slots__}, "request_warnings": ("cwd-mismatch: x",)})
        )
        self.assertIn("\nrequest_warnings:\n- cwd-mismatch: x\n", shown)


class CliWarningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.brain = self.root / "brain"
        self.brain.mkdir()
        attach_current_model(self.brain)
        self.workdir = self.root / "work"
        self.workdir.mkdir()

    def run_open(self, *args: str, env_extra: dict[str, str] | None = None):
        env = {k: v for k, v in os.environ.items() if k not in MARKERS}
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "session_open.py"), "--brain-root", str(self.brain),
             "--session-id", "ses-warn", *args],
            text=True, capture_output=True, check=False, env=env, cwd=self.workdir,
        )

    def test_a_different_cwd_warns_on_stderr_and_in_the_digest_but_succeeds(self) -> None:
        result = self.run_open("--runtime", "codex", "--cwd", str(self.root / "other"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count("cwd-mismatch"), 1)
        self.assertIn("\nrequest_warnings:\n- cwd-mismatch:", result.stdout)
        self.assertIn(f"cd {self.root / 'other'} && codex resume ses-warn", result.stdout)

    def test_matching_cwd_and_runtime_stay_silent(self) -> None:
        result = self.run_open("--runtime", "codex", "--cwd", str(self.workdir),
                               env_extra={"CODEX_SESSION_ID": "ses-warn"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("WARNING", result.stderr)
        self.assertNotIn("request_warnings", result.stdout)

    def test_explicit_runtime_conflicting_with_the_environment_warns(self) -> None:
        result = self.run_open("--runtime", "claude", "--cwd", str(self.workdir),
                               env_extra={"CODEX_SESSION_ID": "secret-value"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("runtime-env-mismatch", result.stderr)
        self.assertNotIn("secret-value", result.stderr + result.stdout)

    def test_omitted_runtime_is_inferred_so_only_ambiguity_can_warn(self) -> None:
        single = self.run_open("--cwd", str(self.workdir), env_extra={"CODEX_SESSION_ID": "a"})
        both = self.run_open("--cwd", str(self.workdir),
                             env_extra={"CODEX_SESSION_ID": "a", "CLAUDE_CODE_SESSION_ID": "b"})

        self.assertNotIn("runtime-env", single.stderr)
        self.assertEqual(both.stderr.count("runtime-env-ambiguous"), 1)

    def test_apply_with_warnings_keeps_exit_status_and_is_idempotent(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        sessions = self.brain / "WIP" / "SESSIONS"
        sessions.mkdir(parents=True)
        (self.brain / "JOURNAL").mkdir()
        (self.brain / "JOURNAL" / f"{today}.md").write_text("# Sessions\n\n# Actions\n", encoding="utf-8")
        (sessions / f"{today}-session-ses-warn-topic.md").write_text(
            "## State\n- Status: open\n\n## Resume command\n- `cd /old && codex resume ses-warn`\n"
            "- Working directory: `/old`\n\n## Current objective\n- keep\n",
            encoding="utf-8",
        )
        args = ("--runtime", "codex", "--cwd", str(self.root / "other"), "--apply")

        first = self.run_open(*args)
        second = self.run_open(*args)

        daily = (self.brain / "JOURNAL" / f"{today}.md").read_text(encoding="utf-8")
        self.assertEqual((first.returncode, second.returncode), (0, 0), first.stderr + second.stderr)
        self.assertIn("cwd-mismatch", first.stderr)
        self.assertEqual(len([line for line in daily.splitlines() if "ses-warn" in line]), 1)


if __name__ == "__main__":
    unittest.main()

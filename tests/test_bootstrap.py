from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "model" / "SCRIPTS" / "bootstrap-zero.sh"


def git(brain: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=brain,
        text=True,
        capture_output=True,
        check=False,
    )


def init_repo(brain: Path) -> None:
    self_result = git(brain, "init", "-q")
    if self_result.returncode != 0:
        raise RuntimeError(self_result.stderr)
    git(brain, "config", "user.email", "tests@example.invalid")
    git(brain, "config", "user.name", "agent-brain tests")
    (brain / "seed.md").write_text("seed\n", encoding="utf-8")
    git(brain, "add", "seed.md")
    result = git(brain, "commit", "-qm", "fixture")
    if result.returncode != 0:
        raise RuntimeError(result.stderr)


def run_bootstrap(
    brain: Path,
    home: Path,
    *,
    apply: bool,
) -> subprocess.CompletedProcess[str]:
    command = [
        "bash",
        str(SCRIPT),
        "--brain",
        str(brain),
        "--runtime",
        "codex",
    ]
    if apply:
        command.append("--apply")
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_EDITOR": "false",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


class BootstrapTests(unittest.TestCase):
    def test_explicit_brain_never_needs_interactive_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            home = root / "home"
            brain.mkdir()
            home.mkdir()

            result = run_bootstrap(brain, home, apply=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"BRAIN = {brain}", result.stdout)
        self.assertNotIn("Brain path:", result.stdout)

    def test_clean_repo_snapshot_is_annotated_unsigned_and_noninteractive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            home = root / "home"
            brain.mkdir()
            home.mkdir()
            init_repo(brain)
            git(brain, "config", "tag.gpgSign", "true")

            result = run_bootstrap(brain, home, apply=True)
            tags = git(brain, "tag", "--list", "pre-bootstrap-*").stdout.splitlines()
            tag_type = git(brain, "cat-file", "-t", tags[0]).stdout.strip() if tags else ""
            tag_message = git(brain, "for-each-ref", "--format=%(contents)", f"refs/tags/{tags[0]}").stdout if tags else ""

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(tags), 1)
        self.assertEqual(tag_type, "tag")
        self.assertIn("agent-brain: pre-bootstrap snapshot", tag_message)
        self.assertNotIn("editor", result.stderr.lower())
        self.assertNotIn("gpg", result.stderr.lower())

    def test_dirty_repo_aborts_without_changing_history_or_index(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            home = root / "home"
            brain.mkdir()
            home.mkdir()
            init_repo(brain)
            (brain / "seed.md").write_text("dirty\n", encoding="utf-8")
            head_before = git(brain, "rev-parse", "HEAD").stdout.strip()
            status_before = git(brain, "status", "--porcelain=v1").stdout

            result = run_bootstrap(brain, home, apply=True)
            head_after = git(brain, "rev-parse", "HEAD").stdout.strip()
            status_after = git(brain, "status", "--porcelain=v1").stdout
            tags = git(brain, "tag", "--list", "pre-bootstrap-*").stdout.splitlines()

        self.assertEqual(result.returncode, 3)
        self.assertIn("dirty working tree", result.stderr)
        self.assertEqual(head_before, head_after)
        self.assertEqual(status_before, status_after)
        self.assertEqual(tags, [])

    def test_non_repo_gets_deterministic_snapshot_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            home = root / "home"
            brain.mkdir()
            home.mkdir()
            (brain / "seed.md").write_text("seed\n", encoding="utf-8")

            result = run_bootstrap(brain, home, apply=True)
            commit_message = git(brain, "log", "-1", "--format=%s").stdout.strip()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commit_message, "agent-brain: pre-bootstrap snapshot")


if __name__ == "__main__":
    unittest.main()

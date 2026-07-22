from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "brain" / "scripts" / "session_close.py"
MODEL_ROOT = REPO_ROOT / "model"
sys.path.insert(0, str(SCRIPT.parent))

import session_close  # noqa: E402


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def git(brain: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=brain,
        text=True,
        capture_output=True,
        check=False,
    )


def create_note(brain: Path, session_id: str, status: str = "open") -> Path:
    brain.mkdir(parents=True, exist_ok=True)
    common_link = brain / "_COMMON"
    if not common_link.exists() and not common_link.is_symlink():
        common_link.symlink_to(MODEL_ROOT, target_is_directory=True)
    note = brain / "WIP" / "SESSIONS" / f"2026-07-21-session-{session_id}-test.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\ntags: [session, wip]\n---\n"
        f"# Session {session_id}\n\n"
        "## State\n"
        f"- Status: {status}\n\n"
        "## Immediate next step\n- none\n",
        encoding="utf-8",
    )
    return note


class SessionCloseTests(unittest.TestCase):
    def test_refuses_unimplanted_brain_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            note = create_note(brain, "session-unsafe")
            (brain / "_COMMON").unlink()
            original = note.read_text(encoding="utf-8")

            result = run(
                "--brain-root",
                str(brain),
                "--apply",
                "handoff",
                "session-unsafe",
            )
            content = note.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 2)
        self.assertIn("not attached to the current agent-brain model", result.stderr)
        self.assertEqual(content, original)

    def test_refuses_brain_attached_to_another_model_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            old_model = root / "obsidian-vault-common"
            old_model.mkdir()
            note = create_note(brain, "session-unsafe")
            (brain / "_COMMON").unlink()
            (brain / "_COMMON").symlink_to(old_model, target_is_directory=True)
            original = note.read_text(encoding="utf-8")

            result = run(
                "--brain-root",
                str(brain),
                "--apply",
                "consolidate",
                "session-unsafe",
            )
            content = note.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 2)
        self.assertIn("conflict-wrong-target", result.stderr)
        self.assertEqual(content, original)

    def test_dry_run_does_not_mutate_note(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            note = create_note(brain, "session-123")
            original = note.read_text(encoding="utf-8")

            result = run(
                "--brain-root",
                str(brain),
                "consolidate",
                "session-123",
            )
            content = note.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(content, original)
        self.assertIn("would update", result.stdout)

    def test_consolidate_is_idempotent_without_archive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            note = create_note(brain, "session-123")
            command = (
                "--brain-root",
                str(brain),
                "--apply",
                "consolidate",
                "session-123",
            )
            first = run(*command)
            content_after_first = note.read_text(encoding="utf-8")
            second = run(*command)
            content_after_second = note.read_text(encoding="utf-8")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(content_after_first, content_after_second)
        self.assertIn("- Status: consolidated", content_after_second)
        self.assertIn("tags: [session]", content_after_second)
        self.assertIn("Status already consolidated", second.stdout)

    def test_handoff_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            note = create_note(brain, "session-123")
            command = (
                "--brain-root",
                str(brain),
                "--apply",
                "handoff",
                "session-123",
            )
            first = run(*command)
            second = run(*command)
            content = note.read_text(encoding="utf-8")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("- Status: handoff-only", content)
        self.assertIn("Status already handoff-only", second.stdout)

    def test_handoff_accepts_trailing_apply(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            note = create_note(brain, "session-123")

            result = run(
                "--brain-root",
                str(brain),
                "handoff",
                "session-123",
                "--apply",
            )
            content = note.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- Status: handoff-only", content)

    def test_archive_refuses_untracked_note_without_mutating_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.assertEqual(git(brain, "init", "-q").returncode, 0)
            note = create_note(brain, "session-123")
            original = note.read_text(encoding="utf-8")

            result = run(
                "--brain-root",
                str(brain),
                "--apply",
                "consolidate",
                "session-123",
                "--archive",
            )

            content = note.read_text(encoding="utf-8")
            archived = brain / "QUARANTINE" / "TRASH" / note.name
            archived_exists = archived.exists()

        self.assertEqual(result.returncode, 1)
        self.assertIn("not tracked by Git", result.stderr)
        self.assertEqual(content, original)
        self.assertFalse(archived_exists)

    def test_archive_dry_run_reports_untracked_note(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.assertEqual(git(brain, "init", "-q").returncode, 0)
            note = create_note(brain, "session-123")
            original = note.read_text(encoding="utf-8")

            result = run(
                "--brain-root",
                str(brain),
                "consolidate",
                "session-123",
                "--archive",
            )
            content = note.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 1)
        self.assertIn("not tracked by Git", result.stderr)
        self.assertEqual(content, original)

    def test_tracked_archive_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.assertEqual(git(brain, "init", "-q").returncode, 0)
            git(brain, "config", "user.email", "tests@example.invalid")
            git(brain, "config", "user.name", "agent-brain tests")
            note = create_note(brain, "session-123")
            git(brain, "add", str(note.relative_to(brain)))
            self.assertEqual(git(brain, "commit", "-qm", "fixture").returncode, 0)
            command = (
                "--brain-root",
                str(brain),
                "--apply",
                "consolidate",
                "session-123",
                "--archive",
            )
            first = run(*command)
            archived = brain / "QUARANTINE" / "TRASH" / note.name
            first_content = archived.read_text(encoding="utf-8")
            archived_rel = archived.relative_to(brain)
            staged_content = git(brain, "show", f":{archived_rel}")
            unstaged_diff = git(brain, "diff", "--quiet", "--", str(archived_rel))
            second = run(*command)
            second_content = archived.read_text(encoding="utf-8")
            note_exists = note.exists()

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertFalse(note_exists)
        self.assertEqual(first_content, second_content)
        self.assertIn("- Status: consolidated", second_content)
        self.assertNotIn("wip", second_content.split("---", 2)[1])
        self.assertEqual(staged_content.returncode, 0, staged_content.stderr)
        self.assertEqual(staged_content.stdout, first_content)
        self.assertEqual(unstaged_diff.returncode, 0, unstaged_diff.stderr)
        self.assertIn("already consolidated and archived", second.stdout)

    def test_tracked_archive_accepts_apply_after_archive_option(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.assertEqual(git(brain, "init", "-q").returncode, 0)
            git(brain, "config", "user.email", "tests@example.invalid")
            git(brain, "config", "user.name", "agent-brain tests")
            note = create_note(brain, "session-123")
            git(brain, "add", str(note.relative_to(brain)))
            self.assertEqual(git(brain, "commit", "-qm", "fixture").returncode, 0)

            result = run(
                "--brain-root",
                str(brain),
                "consolidate",
                "session-123",
                "--archive",
                "--apply",
            )
            archived = brain / "QUARANTINE" / "TRASH" / note.name
            archived_content = archived.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- Status: consolidated", archived_content)
        self.assertNotIn("wip", archived_content.split("---", 2)[1])

    def test_archive_failure_rolls_back_note_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.assertEqual(git(brain, "init", "-q").returncode, 0)
            git(brain, "config", "user.email", "tests@example.invalid")
            git(brain, "config", "user.name", "agent-brain tests")
            note = create_note(brain, "session-123")
            git(brain, "add", str(note.relative_to(brain)))
            self.assertEqual(git(brain, "commit", "-qm", "fixture").returncode, 0)
            original = note.read_text(encoding="utf-8")
            argv = [
                str(SCRIPT),
                "--brain-root",
                str(brain),
                "--apply",
                "consolidate",
                "session-123",
                "--archive",
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(session_close, "git_mv", return_value=False),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                result = session_close.main()
            content = note.read_text(encoding="utf-8")

        self.assertEqual(result, 1)
        self.assertEqual(content, original)

    def test_archive_staging_failure_rolls_back_path_content_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.assertEqual(git(brain, "init", "-q").returncode, 0)
            git(brain, "config", "user.email", "tests@example.invalid")
            git(brain, "config", "user.name", "agent-brain tests")
            note = create_note(brain, "session-123")
            git(brain, "add", str(note.relative_to(brain)))
            self.assertEqual(git(brain, "commit", "-qm", "fixture").returncode, 0)
            original = note.read_text(encoding="utf-8")
            archived = brain / "QUARANTINE" / "TRASH" / note.name
            argv = [
                str(SCRIPT),
                "--brain-root",
                str(brain),
                "--apply",
                "consolidate",
                "session-123",
                "--archive",
            ]

            captured_stderr = io.StringIO()
            with (
                patch.object(sys, "argv", argv),
                patch.object(session_close, "git_stage", return_value=False),
                redirect_stdout(io.StringIO()),
                redirect_stderr(captured_stderr),
            ):
                result = session_close.main()
            content = note.read_text(encoding="utf-8")
            note_exists = note.exists()
            archived_exists = archived.exists()
            status = git(brain, "status", "--porcelain", "--untracked-files=no")

        self.assertEqual(result, 1)
        self.assertTrue(note_exists, captured_stderr.getvalue())
        self.assertFalse(archived_exists)
        self.assertEqual(content, original)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(status.stdout, "")


if __name__ == "__main__":
    unittest.main()

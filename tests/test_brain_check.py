from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "brain" / "scripts"
SCRIPT = SCRIPTS_DIR / "brain_check.py"
sys.path.insert(0, str(SCRIPTS_DIR))

from brain_check import validate_wip_registration  # noqa: E402


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def create_session_fixture(
    brain: Path,
    session_id: str,
    note_dir: Path,
    *,
    command: str,
    status: str = "consolidated",
) -> Path:
    note_dir.mkdir(parents=True, exist_ok=True)
    note = note_dir / f"2026-07-21-session-{session_id}-test.md"
    note.write_text(
        f"---\ntags: [session{', wip' if status != 'consolidated' else ''}]\n---\n"
        f"# Session {session_id}\n\n"
        f"## State\n- Status: {status}\n\n"
        f"## Resume command\n- `{command}`\n"
        "- Working directory: `/workspace/project`\n",
        encoding="utf-8",
    )
    journal = brain / "JOURNAL"
    journal.mkdir(parents=True, exist_ok=True)
    (journal / "2026-07-21.md").write_text(
        "# Sessions\n"
        f"- `{command}` — project. Session note: [[{note.stem}]].\n\n"
        "# Actions\n",
        encoding="utf-8",
    )
    return note


class BrainCheckTests(unittest.TestCase):
    def test_archived_session_note_passes_session_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            session_id = "session-123"
            command = f"cd /workspace/project && codex resume {session_id}"
            create_session_fixture(
                brain,
                session_id,
                brain / "QUARANTINE" / "TRASH",
                command=command,
            )

            result = run(
                "--brain-root",
                str(brain),
                "--session-id",
                session_id,
                "--runtime",
                "codex",
                "--cwd",
                "/workspace/project",
                "--date",
                "2026-07-21",
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Brain postcondition check: OK", result.stdout)

    def test_active_session_note_is_preferred_over_archived_copy(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            session_id = "session-123"
            expected_command = f"cd /workspace/project && codex resume {session_id}"
            create_session_fixture(
                brain,
                session_id,
                brain / "WIP" / "SESSIONS",
                command=expected_command,
                status="open",
            )
            archived = brain / "QUARANTINE" / "TRASH"
            archived.mkdir(parents=True)
            (archived / f"2026-07-20-session-{session_id}-old.md").write_text(
                "# Archived session\n\n"
                "## Resume command\n- `codex resume wrong-session`\n",
                encoding="utf-8",
            )

            result = run(
                "--brain-root",
                str(brain),
                "--session-id",
                session_id,
                "--runtime",
                "codex",
                "--cwd",
                "/workspace/project",
                "--date",
                "2026-07-21",
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Brain postcondition check: OK", result.stdout)

    def test_registered_wip_note_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            (brain / "WIP").mkdir()
            (brain / "WIP" / "agent-brain.md").write_text("# agent-brain\n")
            (brain / "WIP" / "WIP.md").write_text(
                "# WIP\n- [[agent-brain]] — active\n",
                encoding="utf-8",
            )
            errors = validate_wip_registration(brain, "WIP/agent-brain.md")
        self.assertEqual(errors, [])

    def test_unregistered_wip_note_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            (brain / "WIP").mkdir()
            (brain / "WIP" / "agent-brain.md").write_text("# agent-brain\n")
            (brain / "WIP" / "WIP.md").write_text("# WIP\n", encoding="utf-8")
            errors = validate_wip_registration(brain, "WIP/agent-brain.md")
        self.assertTrue(any("not registered" in error for error in errors))

    def test_markdown_link_registration_passes_for_generic_brain(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            (brain / "WIP" / "projects").mkdir(parents=True)
            (brain / "WIP" / "projects" / "agent-brain.md").write_text(
                "# agent-brain\n",
                encoding="utf-8",
            )
            (brain / "WIP" / "WIP.md").write_text(
                "# WIP\n- [agent-brain](projects/agent-brain.md) — active\n",
                encoding="utf-8",
            )
            errors = validate_wip_registration(
                brain,
                "WIP/projects/agent-brain.md",
            )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()

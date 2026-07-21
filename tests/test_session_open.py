from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "brain" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from session_open import (  # noqa: E402
    build_sessions_entry,
    find_daily_template,
    instantiate_daily_template,
    instantiate_session_template,
    resume_command,
    upsert_sessions_entry,
    validate_session_postconditions,
)


class SessionRecoveryTests(unittest.TestCase):
    def test_codex_resume_command_contains_original_cwd(self) -> None:
        self.assertEqual(
            resume_command("codex", "session-123", "/workspace/project"),
            "cd /workspace/project && codex resume session-123",
        )

    def test_resume_command_quotes_cwd(self) -> None:
        self.assertEqual(
            resume_command("claude", "session-123", "/workspace/my project"),
            "cd '/workspace/my project' && claude --resume session-123",
        )

    def test_daily_entry_is_paste_ready(self) -> None:
        entry = build_sessions_entry(
            "session-123",
            "agent-brain",
            "2026-07-21-session-session-123-agent-brain",
            "codex",
            "/workspace/agent-brain",
        )
        self.assertIn(
            "`cd /workspace/agent-brain && codex resume session-123`",
            entry,
        )

    def test_session_note_records_command_and_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            template = Path(raw) / "template.md"
            template.write_text(
                "# Session <date> / <topic> / <id>\n\n"
                "## Resume command\n- placeholder\n\n"
                "## Current objective\n-\n",
                encoding="utf-8",
            )
            note = instantiate_session_template(
                template,
                "2026-07-21",
                "agent-brain",
                "session-123",
                "codex",
                "/workspace/agent-brain",
            )
        self.assertIn(
            "- `cd /workspace/agent-brain && codex resume session-123`",
            note,
        )
        self.assertIn("- Working directory: `/workspace/agent-brain`", note)

    def test_daily_template_is_prepared_with_empty_sessions_block(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            template = Path(raw) / "daily.md"
            template.write_text(
                "---\ntags: [daily]\n---\n"
                "[[<% tp.date.yesterday() %>]] <- x -> "
                "[[<% tp.date.tomorrow() %>]]\n"
                "<% tp.file.cursor() %>\n\n"
                "# Sessions\n"
                "- REPLACE WITH REAL SESSION_ID: placeholder\n"
                "- Example (Codex): `codex resume uuid`\n\n"
                "# Actions\n* [[WORK]]:\n",
                encoding="utf-8",
            )
            daily = instantiate_daily_template(template, "2026-07-21")
        self.assertIn("[[2026-07-20]] <- x -> [[2026-07-22]]", daily)
        self.assertIn("# Sessions\n\n# Actions", daily)
        self.assertNotIn("REPLACE WITH REAL", daily)
        self.assertNotIn("Example (Codex)", daily)
        self.assertNotIn("tp.file.cursor", daily)

    def test_daily_template_divergence_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            templates = brain / "TEMPLATES"
            common_templates = brain / "_COMMON" / "TEMPLATES"
            templates.mkdir(parents=True)
            common_templates.mkdir(parents=True)
            (templates / "Daily Note Template.md").write_text("local\n", encoding="utf-8")
            (common_templates / "TEMPLATE.daily-note.common.md").write_text(
                "common\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "templates diverge"):
                find_daily_template(brain)

    def test_daily_registration_is_idempotent_and_preserves_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            daily = Path(raw) / "2026-07-21.md"
            daily.write_text(
                "# Sessions\n"
                "- REPLACE WITH REAL SESSION_ID: placeholder\n"
                "- Example (Codex): `codex resume uuid`\n"
                "- `codex resume session-123` — user-edited summary\n"
                "- `codex resume session-123` — duplicate\n\n"
                "# Actions\n",
                encoding="utf-8",
            )
            desired = build_sessions_entry(
                "session-123",
                "agent-brain",
                "2026-07-21-session-session-123-agent-brain",
                "codex",
                "/workspace/agent-brain",
            )
            first = upsert_sessions_entry(
                daily,
                desired,
                "session-123",
                apply=True,
            )
            first_content = daily.read_text(encoding="utf-8")
            second = upsert_sessions_entry(
                daily,
                desired,
                "session-123",
                apply=True,
            )
            second_content = daily.read_text(encoding="utf-8")

        self.assertEqual(first, "updated")
        self.assertEqual(second, "unchanged")
        self.assertEqual(first_content, second_content)
        self.assertEqual(first_content.count("session-123"), 1)
        self.assertIn("user-edited summary", first_content)
        self.assertIn(
            "cd /workspace/agent-brain && codex resume session-123",
            first_content,
        )
        self.assertNotIn("REPLACE WITH REAL", first_content)
        self.assertNotIn("Example (Codex)", first_content)

    def test_postconditions_detect_duplicate_daily_registration(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            daily = root / "daily.md"
            note = root / "session.md"
            command = "cd /workspace/project && codex resume session-123"
            daily.write_text(
                f"# Sessions\n- `{command}`\n- `{command}`\n\n# Actions\n",
                encoding="utf-8",
            )
            note.write_text(
                f"## Resume command\n- `{command}`\n"
                "- Working directory: `/workspace/project`\n",
                encoding="utf-8",
            )
            errors = validate_session_postconditions(
                daily,
                note,
                "session-123",
                "codex",
                "/workspace/project",
            )
        self.assertTrue(any("expected one daily registration" in error for error in errors))

    def test_full_apply_can_be_repeated_without_duplicate_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            templates = brain / "TEMPLATES"
            templates.mkdir()
            (templates / "TEMPLATE.daily-note.common.md").write_text(
                "---\ntags: [daily]\n---\n"
                "[[<% tp.date.yesterday() %>]] <- x -> "
                "[[<% tp.date.tomorrow() %>]]\n"
                "<% tp.file.cursor() %>\n\n"
                "# Sessions\n"
                "- REPLACE WITH REAL SESSION_ID: placeholder\n"
                "- Example (Codex): `codex resume uuid`\n\n"
                "# Actions\n* [[WORK]]:\n",
                encoding="utf-8",
            )
            (templates / "TEMPLATE.wip-session.common.md").write_text(
                "---\ntags: [session, wip]\n---\n"
                "# Session <date> / <topic> / <id>\n\n"
                "## State\n- Status: open\n\n"
                "## Resume command\n- placeholder\n\n"
                "## Current objective\n-\n",
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(SCRIPTS_DIR / "session_open.py"),
                "--brain-root",
                str(brain),
                "--session-id",
                "session-123",
                "--runtime",
                "codex",
                "--cwd",
                "/workspace/project",
                "--prepare-daily",
                "--apply",
            ]
            first = subprocess.run(command, text=True, capture_output=True, check=False)
            second = subprocess.run(command, text=True, capture_output=True, check=False)
            today = datetime.now().strftime("%Y-%m-%d")
            daily = (brain / "JOURNAL" / f"{today}.md").read_text(encoding="utf-8")
            session_notes = list((brain / "WIP" / "SESSIONS").glob("*.md"))

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("daily_registration: unchanged", second.stdout)
        self.assertEqual(
            len([line for line in daily.splitlines() if "session-123" in line]),
            1,
        )
        self.assertEqual(len(session_notes), 1)
        self.assertNotIn("REPLACE WITH REAL", daily)

    def test_multiple_sessions_preserve_each_others_daily_entries(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            templates = brain / "TEMPLATES"
            templates.mkdir()
            (templates / "TEMPLATE.wip-session.common.md").write_text(
                "---\ntags: [session, wip]\n---\n"
                "# Session <date> / <topic> / <id>\n\n"
                "## State\n- Status: open\n\n"
                "## Resume command\n- placeholder\n\n"
                "## Current objective\n-\n",
                encoding="utf-8",
            )
            today = datetime.now().strftime("%Y-%m-%d")
            daily_path = brain / "JOURNAL" / f"{today}.md"
            daily_path.parent.mkdir()
            daily_path.write_text("# Sessions\n\n# Actions\n", encoding="utf-8")

            base_command = [
                sys.executable,
                str(SCRIPTS_DIR / "session_open.py"),
                "--brain-root",
                str(brain),
                "--runtime",
                "codex",
                "--cwd",
                "/workspace/project",
                "--apply",
            ]
            results = []
            for session_id in ("session-a", "session-b", "session-a", "session-b"):
                results.append(
                    subprocess.run(
                        base_command + ["--session-id", session_id],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                )
            daily = daily_path.read_text(encoding="utf-8")
            session_lines = [
                line for line in daily.splitlines() if "codex resume session-" in line
            ]
            session_notes = list((brain / "WIP" / "SESSIONS").glob("*.md"))

        self.assertTrue(all(result.returncode == 0 for result in results))
        self.assertEqual(len(session_lines), 2)
        self.assertEqual(sum("session-a" in line for line in session_lines), 1)
        self.assertEqual(sum("session-b" in line for line in session_lines), 1)
        self.assertEqual(len(session_notes), 2)


if __name__ == "__main__":
    unittest.main()

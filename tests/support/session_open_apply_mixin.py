from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from tests.support.session_open_test_support import SCRIPTS_DIR


class SessionOpenApplyMixin:
    def test_full_apply_can_be_repeated_without_duplicate_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.attach_current_model(brain)
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
            today_date = datetime.now().date()
            previous_date = today_date - timedelta(days=7)
            journal = brain / "JOURNAL"
            journal.mkdir()
            previous_daily = journal / f"{previous_date}.md"
            previous_daily.write_text(
                f"[[{previous_date - timedelta(days=1)}]] <- x -> "
                f"[[{previous_date + timedelta(days=1)}]]\n",
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
            today = str(today_date)
            daily = (brain / "JOURNAL" / f"{today}.md").read_text(encoding="utf-8")
            previous_content = previous_daily.read_text(encoding="utf-8")
            session_notes = list((brain / "WIP" / "SESSIONS").glob("*.md"))

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("daily_navigation: OK", first.stdout)
        self.assertIn("daily_registration: unchanged", second.stdout)
        self.assertEqual(
            len([line for line in daily.splitlines() if "session-123" in line]),
            1,
        )
        self.assertEqual(len(session_notes), 1)
        self.assertNotIn("REPLACE WITH REAL", daily)
        self.assertIn(
            f"[[{previous_date}]] <- x -> [[{today_date + timedelta(days=1)}]]",
            daily,
        )
        self.assertIn(f"-> [[{today_date}]]", previous_content)

    def test_prior_day_continuation_reuses_note_and_refreshes_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.attach_current_model(brain)
            session_id = "session-prior-day-full-id"
            today = datetime.now().date()
            prior_day = today - timedelta(days=1)
            prior_stem = f"{prior_day}-session-{session_id}-old-topic"
            session_dir = brain / "WIP" / "SESSIONS"
            session_dir.mkdir(parents=True)
            prior_note = session_dir / f"{prior_stem}.md"
            prior_note.write_text(
                "## State\n- Status: open\n\n"
                "## Resume command\n"
                f"- `cd /old/cwd && codex resume {session_id}`\n"
                "- Working directory: `/old/cwd`\n\n"
                "## Current objective\n- preserve me\n",
                encoding="utf-8",
            )
            daily = brain / "JOURNAL" / f"{today}.md"
            daily.parent.mkdir()
            daily.write_text("# Sessions\n\n# Actions\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "session_open.py"),
                    "--brain-root",
                    str(brain),
                    "--session-id",
                    session_id,
                    "--runtime",
                    "codex",
                    "--cwd",
                    "/workspace/new-project",
                    "--apply",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            notes = list(session_dir.glob("*.md"))
            note_content = prior_note.read_text(encoding="utf-8")
            daily_content = daily.read_text(encoding="utf-8")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(notes, [prior_note])
            self.assertFalse(
                (session_dir / f"{today}-session-{session_id}-new-project.md").exists()
            )
            self.assertIn(
                f"cd /workspace/new-project && codex resume {session_id}",
                note_content,
            )
            self.assertIn(
                "- Working directory: `/workspace/new-project`",
                note_content,
            )
            self.assertIn("## Current objective\n- preserve me", note_content)
            registrations = [
                line for line in daily_content.splitlines() if session_id in line
            ]
            self.assertEqual(len(registrations), 1)
            self.assertIn(f"[[{prior_stem}]]", registrations[0])

    def test_multiple_sessions_preserve_each_others_daily_entries(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.attach_current_model(brain)
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

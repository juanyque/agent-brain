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

    def _write_closed_note(
        self, session_dir: Path, session_id: str, prior_day, status: str
    ) -> Path:
        note = session_dir / f"{prior_day}-session-{session_id}-topic.md"
        state_block = (
            f"## State\n- Status: {status}\n\n" if status else "## State\n\n"
        )
        note.write_text(
            state_block
            + "## Resume command\n"
            f"- `cd /old && opencode -s {session_id}`\n"
            "- Working directory: `/old`\n\n"
            "## Current objective\n- preserve me\n",
            encoding="utf-8",
        )
        return note

    def _run_resume(
        self, brain: Path, session_id: str, *extra: str
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "session_open.py"),
                "--brain-root", str(brain),
                "--session-id", session_id,
                "--runtime", "opencode",
                "--cwd", "/new-project",
                *extra,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_consolidated_resume_is_refused_without_explicit_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.attach_current_model(brain)
            session_id = "session-consolidated-full-id"
            today = datetime.now().date()
            session_dir = brain / "WIP" / "SESSIONS"
            session_dir.mkdir(parents=True)
            note = self._write_closed_note(
                session_dir, session_id, today - timedelta(days=1), "consolidated"
            )
            daily = brain / "JOURNAL" / f"{today}.md"
            daily.parent.mkdir()
            original_daily = "# Sessions\n\n# Actions\n"
            daily.write_text(original_daily, encoding="utf-8")
            original_note = note.read_text(encoding="utf-8")

            result = self._run_resume(brain, session_id, "--apply")

            daily_content = daily.read_text(encoding="utf-8")
            note_content = note.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 1)
        self.assertIn("refusing to register it as active", result.stderr)
        self.assertIn("--reopen-consolidated", result.stderr)
        self.assertEqual(daily_content, original_daily)
        self.assertEqual(note_content, original_note)

    def test_reopen_consolidated_records_transition_and_registers_today(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.attach_current_model(brain)
            session_id = "session-reopen-full-id"
            today = datetime.now().date()
            prior_day = today - timedelta(days=1)
            prior_stem = f"{prior_day}-session-{session_id}-topic"
            session_dir = brain / "WIP" / "SESSIONS"
            session_dir.mkdir(parents=True)
            note = self._write_closed_note(session_dir, session_id, prior_day, "consolidated")
            daily = brain / "JOURNAL" / f"{today}.md"
            daily.parent.mkdir()
            daily.write_text("# Sessions\n\n# Actions\n", encoding="utf-8")

            result = self._run_resume(brain, session_id, "--reopen-consolidated", "--apply")

            note_content = note.read_text(encoding="utf-8")
            registrations = [
                line
                for line in daily.read_text(encoding="utf-8").splitlines()
                if session_id in line
            ]
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("reopened:", result.stdout)
        self.assertIn("- Status: open\n- Reopened: " f"{today} (from consolidated)", note_content)
        self.assertIn(f"cd /new-project && opencode -s {session_id}", note_content)
        self.assertIn("## Current objective\n- preserve me", note_content)
        self.assertEqual(len(registrations), 1)
        self.assertIn(f"[[{prior_stem}]]", registrations[0])

    def test_stale_follow_up_resume_is_refused_like_consolidated(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.attach_current_model(brain)
            session_id = "session-stale-full-id"
            today = datetime.now().date()
            session_dir = brain / "WIP" / "SESSIONS"
            session_dir.mkdir(parents=True)
            self._write_closed_note(
                session_dir, session_id, today - timedelta(days=1), "stale-follow-up"
            )
            daily = brain / "JOURNAL" / f"{today}.md"
            daily.parent.mkdir()
            daily.write_text("# Sessions\n\n# Actions\n", encoding="utf-8")

            result = self._run_resume(brain, session_id, "--apply")

            daily_content = daily.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 1)
        self.assertIn("session note is stale-follow-up", result.stderr)
        self.assertNotIn(session_id, daily_content)

    def test_handoff_only_resume_still_registers_without_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.attach_current_model(brain)
            session_id = "session-handoff-full-id"
            today = datetime.now().date()
            session_dir = brain / "WIP" / "SESSIONS"
            session_dir.mkdir(parents=True)
            note = self._write_closed_note(
                session_dir, session_id, today - timedelta(days=1), "handoff-only"
            )
            daily = brain / "JOURNAL" / f"{today}.md"
            daily.parent.mkdir()
            daily.write_text("# Sessions\n\n# Actions\n", encoding="utf-8")

            result = self._run_resume(brain, session_id, "--apply")

            note_content = note.read_text(encoding="utf-8")
            registrations = [
                line
                for line in daily.read_text(encoding="utf-8").splitlines()
                if session_id in line
            ]
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("- Status: handoff-only", note_content)
        self.assertNotIn("Reopened:", note_content)
        self.assertEqual(len(registrations), 1)
    def test_dry_run_on_consolidated_warns_and_refuses_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.attach_current_model(brain)
            session_id = "session-drywarn-full-id"
            today = datetime.now().date()
            session_dir = brain / "WIP" / "SESSIONS"
            session_dir.mkdir(parents=True)
            note = self._write_closed_note(
                session_dir, session_id, today - timedelta(days=1), "consolidated"
            )
            original_note = note.read_text(encoding="utf-8")

            result = self._run_resume(brain, session_id)

            note_content = note.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("consolidated_note:", result.stdout)
        self.assertIn("--reopen-consolidated", result.stdout)
        self.assertEqual(note_content, original_note)

    def test_legacy_note_without_status_still_resumes_via_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.attach_current_model(brain)
            session_id = "session-legacy-full-id"
            today = datetime.now().date()
            session_dir = brain / "WIP" / "SESSIONS"
            session_dir.mkdir(parents=True)
            note = self._write_closed_note(
                session_dir, session_id, today - timedelta(days=2), ""
            )
            daily = brain / "JOURNAL" / f"{today}.md"
            daily.parent.mkdir()
            daily.write_text("# Sessions\n\n# Actions\n", encoding="utf-8")

            result = self._run_resume(brain, session_id, "--apply")

            note_content = note.read_text(encoding="utf-8")
            registrations = [
                line
                for line in daily.read_text(encoding="utf-8").splitlines()
                if session_id in line
            ]
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(registrations), 1)
        self.assertNotIn("Status:", note_content)

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

from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.support.session_open_test_support import (
    find_daily_template,
    prepare_daily_note,
    session_open,
    snapshot_tree,
    upsert_sessions_entry,
    validate_daily_navigation,
    validate_session_postconditions,
)


class SessionOpenDailyFailureMixin:
    def test_prepare_daily_rolls_back_all_files_when_neighbor_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            templates = brain / "TEMPLATES"
            templates.mkdir()
            (templates / "TEMPLATE.daily-note.common.md").write_text(
                "[[<% tp.date.yesterday() %>]] <- x -> "
                "[[<% tp.date.tomorrow() %>]]\n\n"
                "# Sessions\n\n# Actions\n",
                encoding="utf-8",
            )
            journal = brain / "JOURNAL"
            journal.mkdir()
            previous = journal / "2026-07-15.md"
            original = "[[2026-07-14]] <- x -> [[2026-07-16]]\n# Existing\n"
            previous.write_text(original, encoding="utf-8")
            today = journal / "2026-07-22.md"
            failed = False

            def flaky_write(path: Path, content: str) -> None:
                nonlocal failed
                if path == previous and not failed:
                    failed = True
                    path.write_text("partial", encoding="utf-8")
                    raise OSError("simulated neighbor write failure")
                path.write_text(content, encoding="utf-8")

            with patch("session_open._write_text", side_effect=flaky_write):
                with self.assertRaisesRegex(OSError, "simulated neighbor write failure"):
                    prepare_daily_note(brain, today, "2026-07-22", apply=True)
            today_exists = today.exists()
            previous_content = previous.read_text(encoding="utf-8")

        self.assertFalse(today_exists)
        self.assertEqual(previous_content, original)

    def test_prepare_daily_refuses_malformed_neighbor_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            templates = brain / "TEMPLATES"
            templates.mkdir()
            (templates / "TEMPLATE.daily-note.common.md").write_text(
                "[[<% tp.date.yesterday() %>]] <- x -> "
                "[[<% tp.date.tomorrow() %>]]\n\n"
                "# Sessions\n\n# Actions\n",
                encoding="utf-8",
            )
            journal = brain / "JOURNAL"
            journal.mkdir()
            previous = journal / "2026-07-15.md"
            original = "# Daily without navigation\n"
            previous.write_text(original, encoding="utf-8")
            today = journal / "2026-07-22.md"

            with self.assertRaisesRegex(ValueError, "navigation line"):
                prepare_daily_note(brain, today, "2026-07-22", apply=True)
            today_exists = today.exists()
            previous_content = previous.read_text(encoding="utf-8")

        self.assertFalse(today_exists)
        self.assertEqual(previous_content, original)

    def test_navigation_validation_detects_nonreciprocal_gap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            journal = Path(raw) / "JOURNAL"
            journal.mkdir()
            previous = journal / "2026-07-15.md"
            previous.write_text(
                "[[2026-07-14]] <- x -> [[2026-07-16]]\n",
                encoding="utf-8",
            )
            today = journal / "2026-07-22.md"
            today.write_text(
                "[[2026-07-21]] <- x -> [[2026-07-23]]\n",
                encoding="utf-8",
            )

            errors = validate_daily_navigation(journal, today, "2026-07-22")

        self.assertTrue(any("expected 2026-07-15" in error for error in errors))
        self.assertTrue(any("expected 2026-07-22" in error for error in errors))

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

    def test_postconditions_detect_stale_daily_session_link(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            daily = root / "daily.md"
            note = root / "2026-07-22-session-session-123-project.md"
            command = "cd /workspace/project && codex resume session-123"
            daily.write_text(
                f"# Sessions\n- `{command}` — project. "
                "Session note: [[old-session-note]].\n\n# Actions\n",
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

        self.assertIn("daily registration does not link the selected session note", errors)

    def test_registration_write_failure_restores_daily_and_rolls_back_session_note(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.attach_current_model(brain)
            templates = brain / "TEMPLATES"
            templates.mkdir()
            (templates / "TEMPLATE.wip-session.common.md").write_text(
                "# Session <date> / <topic> / <id>\n\n"
                "## Resume command\n- placeholder\n",
                encoding="utf-8",
            )
            today = datetime.now().strftime("%Y-%m-%d")
            daily = brain / "JOURNAL" / f"{today}.md"
            daily.parent.mkdir()
            daily.write_text("# Sessions\n\n# Actions\n", encoding="utf-8")
            before = snapshot_tree(brain)
            actual_upsert = session_open.upsert_sessions_entry

            def fail_apply(
                daily_path: Path,
                entry: str,
                session_id: str,
                apply: bool,
                *,
                safe_root: Path | None = None,
            ) -> str:
                if apply:
                    daily_path.write_bytes(b"partially-mutated daily note\n")
                    raise OSError("injected daily write failure")
                return actual_upsert(
                    daily_path,
                    entry,
                    session_id,
                    apply=False,
                    safe_root=safe_root,
                )

            argv = [
                "session_open.py",
                "--brain-root",
                str(brain),
                "--session-id",
                "session-rollback",
                "--runtime",
                "codex",
                "--cwd",
                "/workspace/project",
                "--apply",
            ]
            with (
                patch("sys.argv", argv),
                patch("session_open.upsert_sessions_entry", side_effect=fail_apply),
            ):
                result = session_open.main()

            self.assertNotEqual(result, 0)
            self.assertEqual(daily.read_bytes(), b"# Sessions\n\n# Actions\n")
            self.assertEqual(list((brain / "WIP" / "SESSIONS").glob("*.md")), [])
            self.assertEqual(snapshot_tree(brain), before)

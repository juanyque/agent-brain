from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from tests.support.session_open_test_support import (
    SCRIPTS_DIR,
    build_sessions_entry,
    daily_navigation_targets,
    prepare_daily_note,
    upsert_sessions_entry,
    validate_daily_navigation,
)


class SessionOpenDailyHappyMixin:
    def test_prepare_daily_links_latest_existing_note_across_gap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            templates = brain / "TEMPLATES"
            templates.mkdir()
            (templates / "TEMPLATE.daily-note.common.md").write_text(
                "---\ntags: [daily]\n---\n"
                "[[<% tp.date.yesterday() %>]] <- x -> "
                "[[<% tp.date.tomorrow() %>]]\n\n"
                "# Sessions\n- REPLACE WITH REAL SESSION_ID: placeholder\n\n"
                "# Actions\n* [[WORK]]:\n",
                encoding="utf-8",
            )
            journal = brain / "JOURNAL"
            journal.mkdir()
            previous = journal / "2026-07-15.md"
            previous.write_text(
                "[[2026-07-14]] <- x -> [[2026-07-16]]\n\n# Existing\n",
                encoding="utf-8",
            )
            today = journal / "2026-07-22.md"

            action = prepare_daily_note(brain, today, "2026-07-22", apply=True)

            today_content = today.read_text(encoding="utf-8")
            previous_content = previous.read_text(encoding="utf-8")

        self.assertEqual(action, "created")
        self.assertIn("[[2026-07-15]] <- x -> [[2026-07-23]]", today_content)
        self.assertIn("[[2026-07-14]] <- x -> [[2026-07-22]]", previous_content)
        self.assertIn("# Existing", previous_content)

    def test_prepare_daily_dry_run_leaves_neighbor_unchanged(self) -> None:
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
            original = "[[2026-07-14]] <- x -> [[2026-07-16]]\n"
            previous.write_text(original, encoding="utf-8")
            today = journal / "2026-07-22.md"

            action = prepare_daily_note(brain, today, "2026-07-22", apply=False)
            today_exists = today.exists()
            previous_content = previous.read_text(encoding="utf-8")

        self.assertEqual(action, "would-create")
        self.assertFalse(today_exists)
        self.assertEqual(previous_content, original)

    def test_prepare_daily_backfill_updates_both_existing_neighbors(self) -> None:
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
            previous = journal / "2026-07-05.md"
            previous.write_text(
                "[[2026-07-04]] <- x -> [[2026-07-06]]\n",
                encoding="utf-8",
            )
            following = journal / "2026-07-10.md"
            following.write_text(
                "[[2026-07-09]] <- x -> [[2026-07-11]]\n",
                encoding="utf-8",
            )
            inserted = journal / "2026-07-07.md"

            prepare_daily_note(brain, inserted, "2026-07-07", apply=True)

            errors = validate_daily_navigation(journal, inserted, "2026-07-07")
            inserted_targets = daily_navigation_targets(
                inserted.read_text(encoding="utf-8")
            )
            previous_targets = daily_navigation_targets(
                previous.read_text(encoding="utf-8")
            )
            following_targets = daily_navigation_targets(
                following.read_text(encoding="utf-8")
            )

        self.assertEqual(inserted_targets, ("2026-07-05", "2026-07-10"))
        self.assertEqual(previous_targets[1], "2026-07-07")
        self.assertEqual(following_targets[0], "2026-07-07")
        self.assertEqual(errors, [])

    def test_daily_registration_is_idempotent_and_preserves_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            daily = Path(raw) / "2026-07-21.md"
            daily.write_text(
                "# Sessions\n"
                "- REPLACE WITH REAL SESSION_ID: placeholder\n"
                "- Example (Codex): `codex resume uuid`\n"
                "- `codex resume session-123` — user-edited summary. "
                "Session note: [[old-session-note]].\n"
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
        self.assertEqual(
            len([line for line in first_content.splitlines() if "session-123" in line]),
            1,
        )
        self.assertIn("user-edited summary", first_content)
        self.assertIn(
            "[[2026-07-21-session-session-123-agent-brain]]",
            first_content,
        )
        self.assertNotIn("[[old-session-note]]", first_content)
        self.assertIn(
            "cd /workspace/agent-brain && codex resume session-123",
            first_content,
        )
        self.assertNotIn("REPLACE WITH REAL", first_content)
        self.assertNotIn("Example (Codex)", first_content)

    def test_reopening_archived_session_refreshes_daily_note_link(self) -> None:
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
            session_id = "session-123"
            command = f"cd /workspace/project && codex resume {session_id}"
            archive = brain / "QUARANTINE" / "TRASH"
            archive.mkdir(parents=True)
            archived_stem = f"2026-07-21-session-{session_id}-project"
            (archive / f"{archived_stem}.md").write_text(
                f"## Resume command\n- `{command}`\n",
                encoding="utf-8",
            )
            today = datetime.now().strftime("%Y-%m-%d")
            daily = brain / "JOURNAL" / f"{today}.md"
            daily.parent.mkdir()
            daily.write_text(
                "# Sessions\n"
                f"- `{command}` — carefully edited summary. "
                f"Session note: [[{archived_stem}]].\n\n"
                "# Actions\n",
                encoding="utf-8",
            )

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
                    "/workspace/project",
                    "--apply",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            active_notes = list((brain / "WIP" / "SESSIONS").glob("*.md"))
            daily_content = daily.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(active_notes), 1)
        self.assertIn("daily_registration: updated", result.stdout)
        self.assertIn("carefully edited summary", daily_content)
        self.assertIn(f"[[{active_notes[0].stem}]]", daily_content)
        self.assertNotIn(f"[[{archived_stem}]]", daily_content)

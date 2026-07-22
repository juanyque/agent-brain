from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "brain" / "scripts"
MODEL_ROOT = Path(__file__).resolve().parents[1] / "model"
sys.path.insert(0, str(SCRIPTS_DIR))

from session_open import (  # noqa: E402
    build_sessions_entry,
    daily_navigation_targets,
    extract_wip_context,
    find_daily_template,
    instantiate_daily_template,
    instantiate_session_template,
    list_daily_notes,
    prepare_daily_note,
    resume_command,
    upsert_sessions_entry,
    validate_daily_navigation,
    validate_session_postconditions,
)


class SessionRecoveryTests(unittest.TestCase):
    @staticmethod
    def attach_current_model(brain: Path) -> None:
        (brain / "_COMMON").symlink_to(MODEL_ROOT, target_is_directory=True)

    def test_project_wip_context_surfaces_optional_capability_links(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wip = Path(raw) / "WIP.md"
            wip.write_text(
                "# WIP\n\n"
                "## another-project - Graphify\n"
                "- Registry: [[graphify.registry#another-project]]\n"
                "- Graph: [[graphify.another-project]]\n\n"
                "## all-the-things - Graphify\n"
                "- Registry: [[graphify.registry#all-the-things-card-platform]]\n"
                "- Graph: [[graphify.all-the-things-card-platform]]\n",
                encoding="utf-8",
            )

            context = extract_wip_context(
                wip,
                "/workspace/all-the-things",
            )

        rendered = "\n".join(context)
        self.assertIn("## all-the-things - Graphify", rendered)
        self.assertIn("[[graphify.registry#all-the-things-card-platform]]", rendered)
        self.assertIn("[[graphify.all-the-things-card-platform]]", rendered)
        self.assertNotIn("another-project", rendered)

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

    def test_daily_notes_are_sorted_by_date_across_archive_folders(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            journal = Path(raw) / "JOURNAL"
            archive = journal / "2025"
            archive.mkdir(parents=True)
            (archive / "2025-12-31.md").write_text("old\n", encoding="utf-8")
            (journal / "2026-07-22.md").write_text("current\n", encoding="utf-8")

            notes = list_daily_notes(journal)

        self.assertEqual(
            [path.name for path in notes],
            ["2025-12-31.md", "2026-07-22.md"],
        )

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

    def test_cli_refuses_unimplanted_project_before_dry_run_or_apply(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            templates = project / "TEMPLATES"
            templates.mkdir()
            (templates / "TEMPLATE.wip-session.common.md").write_text(
                "# Session <date> / <topic> / <id>\n",
                encoding="utf-8",
            )
            today = datetime.now().strftime("%Y-%m-%d")
            journal = project / "JOURNAL"
            journal.mkdir()
            daily = journal / f"{today}.md"
            daily.write_text("# Sessions\n\n# Actions\n", encoding="utf-8")
            command = [
                sys.executable,
                str(SCRIPTS_DIR / "session_open.py"),
                "--brain-root",
                str(project),
                "--session-id",
                "session-unsafe",
                "--runtime",
                "codex",
                "--cwd",
                "/workspace/project",
            ]

            dry_run = subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
            )
            apply = subprocess.run(
                command + ["--apply"],
                text=True,
                capture_output=True,
                check=False,
            )
            sessions_dir_exists = (project / "WIP" / "SESSIONS").exists()
            daily_content = daily.read_text(encoding="utf-8")

        self.assertNotEqual(dry_run.returncode, 0)
        self.assertNotEqual(apply.returncode, 0)
        self.assertIn("not attached to the current agent-brain model", dry_run.stderr)
        self.assertIn("not attached to the current agent-brain model", apply.stderr)
        self.assertFalse(sessions_dir_exists)
        self.assertEqual(daily_content, "# Sessions\n\n# Actions\n")

    def test_cli_refuses_common_link_to_another_model(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = root / "project"
            old_model = root / "obsidian-vault-common"
            project.mkdir()
            old_model.mkdir()
            (project / "_COMMON").symlink_to(old_model, target_is_directory=True)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "session_open.py"),
                    "--brain-root",
                    str(project),
                    "--session-id",
                    "session-unsafe",
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
            sessions_dir_exists = (project / "WIP" / "SESSIONS").exists()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("conflict-wrong-target", result.stderr)
        self.assertFalse(sessions_dir_exists)

    def test_cli_refuses_looping_common_link_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            (project / "_COMMON").symlink_to("_COMMON", target_is_directory=True)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "session_open.py"),
                    "--brain-root",
                    str(project),
                    "--session-id",
                    "session-unsafe",
                    "--runtime",
                    "codex",
                    "--apply",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            sessions_dir_exists = (project / "WIP" / "SESSIONS").exists()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("conflict-invalid-target", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(sessions_dir_exists)


if __name__ == "__main__":
    unittest.main()

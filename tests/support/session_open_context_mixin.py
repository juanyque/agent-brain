from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from tests.support.session_open_test_support import (
    SCRIPTS_DIR,
    build_sessions_entry,
    extract_wip_context,
    instantiate_session_template,
    list_daily_notes,
    resume_command,
    snapshot_tree,
)


class SessionOpenContextMixin:
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

    def test_malformed_journal_config_is_surfaced_without_fallback_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.attach_current_model(brain)
            config = brain / ".obsidian" / "daily-notes.json"
            config.parent.mkdir()
            config.write_text('{"folder": "ALT"\n', encoding="utf-8")
            templates = brain / "TEMPLATES"
            templates.mkdir()
            (templates / "TEMPLATE.wip-session.common.md").write_text(
                "# Session <date> / <topic> / <id>\n\n"
                "## Resume command\n- placeholder\n",
                encoding="utf-8",
            )
            today = datetime.now().strftime("%Y-%m-%d")
            fallback_daily = brain / "JOURNAL" / f"{today}.md"
            fallback_daily.parent.mkdir()
            fallback_daily.write_text("# Sessions\n\n# Actions\n", encoding="utf-8")
            before = snapshot_tree(brain)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "session_open.py"),
                    "--brain-root",
                    str(brain),
                    "--session-id",
                    "session-bad-config",
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

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid journal configuration", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(snapshot_tree(brain), before)

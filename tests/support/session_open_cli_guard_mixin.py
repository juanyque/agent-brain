from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from tests.support.session_open_test_support import (
    SCRIPTS_DIR,
    snapshot_tree,
)


class SessionOpenCliGuardMixin:
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

    def test_apply_rejects_symlinked_wip_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            outside = root / "outside"
            brain.mkdir()
            outside.mkdir()
            self.attach_current_model(brain)
            (outside / "sentinel.txt").write_text("unchanged\n", encoding="utf-8")
            (brain / "WIP").symlink_to(outside, target_is_directory=True)
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
            brain_before = snapshot_tree(brain)
            outside_before = snapshot_tree(outside)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "session_open.py"),
                    "--brain-root",
                    str(brain),
                    "--session-id",
                    "session-symlink",
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
            self.assertIn("session note parent is a symlink", result.stderr)
            self.assertEqual(snapshot_tree(brain), brain_before)
            self.assertEqual(snapshot_tree(outside), outside_before)

    def test_invalid_daily_sessions_heading_leaves_no_partial_write(self) -> None:
        for daily_content in ("# Actions\n* unchanged\n", "## Sessions\n\n# Actions\n"):
            with self.subTest(daily_content=daily_content):
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
                    daily.write_text(daily_content, encoding="utf-8")
                    before = snapshot_tree(brain)

                    result = subprocess.run(
                        [
                            sys.executable,
                            str(SCRIPTS_DIR / "session_open.py"),
                            "--brain-root",
                            str(brain),
                            "--session-id",
                            "session-invalid-daily",
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
                    self.assertIn(
                        "session registration failed (missing-header)",
                        result.stderr,
                    )
                    self.assertEqual(snapshot_tree(brain), before)

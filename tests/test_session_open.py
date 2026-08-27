from __future__ import annotations

import unittest
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from tests.support.session_open_apply_mixin import SessionOpenApplyMixin
from tests.support.session_open_cli_guard_mixin import SessionOpenCliGuardMixin
from tests.support.session_open_context_mixin import SessionOpenContextMixin
from tests.support.session_open_daily_failure_mixin import SessionOpenDailyFailureMixin
from tests.support.session_open_daily_happy_mixin import SessionOpenDailyHappyMixin
from tests.support.session_open_daily_template_mixin import SessionOpenDailyTemplateMixin
from tests.support.session_open_neighbor_symlink_mixin import SessionOpenNeighborSymlinkMixin
from tests.support.session_open_race_mixin import SessionOpenRaceMixin
from tests.support.session_open_test_support import (
    SCRIPTS_DIR,
    attach_current_model,
    snapshot_tree,
)
from tests.support.session_open_toctou_mixin import SessionOpenToctouMixin


class SessionRecoveryTests(
    SessionOpenContextMixin,
    SessionOpenDailyTemplateMixin,
    SessionOpenDailyHappyMixin,
    SessionOpenDailyFailureMixin,
    SessionOpenApplyMixin,
    SessionOpenCliGuardMixin,
    SessionOpenRaceMixin,
    SessionOpenToctouMixin,
    SessionOpenNeighborSymlinkMixin,
    unittest.TestCase,
):
    attach_current_model = staticmethod(attach_current_model)


class SessionDryRunTests(unittest.TestCase):
    def test_dry_run_emits_compact_digest_without_mutating_tree(self) -> None:
        sentinel = "UNRELATED_PRIVATE_SENTINEL_TODO17"
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            SessionRecoveryTests.attach_current_model(brain)
            templates = brain / "TEMPLATES"
            templates.mkdir()
            (templates / "TEMPLATE.wip-session.common.md").write_text(
                "# Session <date> / <topic> / <id>\n\n"
                "## State\n- Status: open\n\n"
                "## Resume command\n- placeholder\n",
                encoding="utf-8",
            )
            today = datetime.now().strftime("%Y-%m-%d")
            journal = brain / "JOURNAL"
            journal.mkdir()
            (journal / f"{today}.md").write_text("# Sessions\n\n# Actions\n", encoding="utf-8")
            wip = brain / "WIP"
            wip.mkdir()
            (wip / "WIP.md").write_text(
                "# WIP\n\n"
                "## runtime-project\n"
                "- visible cwd-filtered WIP\n\n"
                "## unrelated-private\n"
                f"- {sentinel}\n",
                encoding="utf-8",
            )
            task_types = brain / "TASK_TYPES"
            task_types.mkdir()
            (task_types / "TASK_TYPES.md").write_text(
                "- [[runtime-task]] Visible task one-liner\n",
                encoding="utf-8",
            )
            before = snapshot_tree(brain)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "session_open.py"),
                    "--brain-root",
                    str(brain),
                    "--session-id",
                    "session-todo17",
                    "--runtime",
                    "codex",
                    "--cwd",
                    "/workspace/runtime-project",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            after = snapshot_tree(brain)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(after, before)
        self.assertIn("# Session open digest", result.stdout)
        self.assertIn("mode: dry-run", result.stdout)
        self.assertIn("visible cwd-filtered WIP", result.stdout)
        self.assertIn("- [[runtime-task]] Visible task one-liner", result.stdout)
        self.assertNotIn(sentinel, result.stdout)
        self.assertNotIn("UNRELATED_PRIVATE_SENTINEL_TODO17", result.stderr)
        # No JOBS_LOGS.md exists in this fixture brain, so every calendar job is
        # genuinely due and must be surfaced automatically, without the user
        # having to say "weekly maintenance".
        self.assertIn("maintenance_jobs:", result.stdout)
        self.assertIn("- Weekly: due", result.stdout)
        self.assertIn("- Monthly: due", result.stdout)
        self.assertIn("- Yearly: due", result.stdout)

    def test_dry_run_omits_maintenance_jobs_block_when_nothing_is_due(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            SessionRecoveryTests.attach_current_model(brain)
            templates = brain / "TEMPLATES"
            templates.mkdir()
            (templates / "TEMPLATE.wip-session.common.md").write_text(
                "# Session <date> / <topic> / <id>\n\n"
                "## State\n- Status: open\n\n"
                "## Resume command\n- placeholder\n",
                encoding="utf-8",
            )
            today_date = datetime.now().date()
            today = today_date.isoformat()
            current_week = f"{today_date.isocalendar().year}-W{today_date.isocalendar().week:02d}"
            current_month = f"{today_date.year}-{today_date.month:02d}"
            journal = brain / "JOURNAL"
            journal.mkdir()
            (journal / f"{today}.md").write_text("# Sessions\n\n# Actions\n", encoding="utf-8")
            (brain / "JOBS_LOGS.md").write_text(
                "## Weekly\n"
                f"- run: {today}\n"
                f"  period: {current_week}\n"
                "  status: done\n"
                "  summary: nothing pending\n"
                "## Monthly\n"
                f"- run: {today}\n"
                f"  period: {current_month}\n"
                "  status: done\n"
                "  summary: nothing pending\n"
                "## Yearly\n"
                f"- run: {today}\n"
                f"  period: {today_date.year}\n"
                "  status: done\n"
                "  summary: nothing pending\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "session_open.py"),
                    "--brain-root",
                    str(brain),
                    "--session-id",
                    "session-quiet-maintenance",
                    "--runtime",
                    "codex",
                    "--cwd",
                    "/workspace/runtime-project",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("maintenance_jobs:", result.stdout)


if __name__ == "__main__":
    unittest.main()

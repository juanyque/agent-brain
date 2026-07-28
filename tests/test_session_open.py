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


if __name__ == "__main__":
    unittest.main()

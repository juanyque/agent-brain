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
        # Source ingestion is an optional capability: WIP.md here never links
        # sources.registry.md, so it must stay dormant and silent.
        self.assertNotIn("sources_due:", result.stdout)

    def _write_sources_fixture(self, brain: Path, *, wip_body: str) -> None:
        """A brain-scoped source-ingestion fixture: registry + a fully resolvable
        descriptor (Access + Schedule fields, a SOURCE_TYPES guide, and an
        environment profile that routes the descriptor's capability) plus a caller-
        supplied WIP.md body, so tests can vary only the activation link."""
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
        (wip / "WIP.md").write_text(wip_body, encoding="utf-8")
        sources = wip / "SOURCES"
        sources.mkdir()
        (sources / "sources.registry.md").write_text(
            "# Source registry\n\n## Sources\n\n"
            "### slack-eng\n- Status: enabled\n- Type: messaging-tool\n",
            encoding="utf-8",
        )
        (sources / "sources.slack-eng.md").write_text(
            "# Source: slack-eng\n\n"
            "## Access\n- Requires capability: chat.search\n- Locator: #eng channel\n\n"
            "## Schedule\n- Check cadence (days): 1\n- Last checked: not checked\n"
            "- Last status: not checked\n",
            encoding="utf-8",
        )
        (brain / "SOURCE_TYPES").mkdir()
        (brain / "SOURCE_TYPES" / "messaging-tool.md").write_text("# messaging-tool\n", encoding="utf-8")
        shared = brain / "_AGENTS" / "SHARED"
        (shared / "profiles").mkdir(parents=True)
        (shared / "environment.json").write_text(
            '{"schema_version": 1, "default_profile": "test", "project_rules": []}',
            encoding="utf-8",
        )
        (shared / "profiles" / "test.json").write_text(
            '{"schema_version": 1, "id": "test", "display_name": "Test", '
            '"providers": {"manual-tool": {"kind": "manual", "service": "manual-tool", '
            '"required": false, "operations": {}}}, '
            '"capability_routes": {"chat.search": ["manual-tool"]}, "projects": []}',
            encoding="utf-8",
        )

    def _run_session_open(self, brain: Path, session_id: str, cwd: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "session_open.py"),
                "--brain-root", str(brain),
                "--session-id", session_id,
                "--runtime", "codex",
                "--cwd", cwd,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_dry_run_surfaces_due_source_when_wip_links_the_registry(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            SessionRecoveryTests.attach_current_model(brain)
            self._write_sources_fixture(
                brain,
                wip_body="# WIP\n\n## Fuentes externas\n\n- [[sources.registry|registry]]\n",
            )

            result = self._run_session_open(brain, "session-sources-active", "/workspace/runtime-project")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sources_due:", result.stdout)
        self.assertIn("- slack-eng (messaging-tool): never checked", result.stdout)

    def test_activation_does_not_depend_on_cwd_matching_any_heading(self) -> None:
        # Source ingestion is brain-scoped (RULES-OPTIONAL-CAPABILITIES.common.md ->
        # "Scopes"): unlike Graphify, activation must not require the cwd to match
        # any WIP.md heading. A cwd that matches nothing in this fixture still
        # activates, because the registry link exists somewhere in WIP.md.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            SessionRecoveryTests.attach_current_model(brain)
            self._write_sources_fixture(
                brain,
                wip_body="# WIP\n\n## Personal dashboard\n\n- [[sources.registry|registry]]\n",
            )

            result = self._run_session_open(
                brain, "session-sources-unrelated-cwd", "/workspace/some-unrelated-checkout"
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sources_due:", result.stdout)
        self.assertIn("- slack-eng (messaging-tool): never checked", result.stdout)

    def test_dry_run_omits_sources_due_when_registry_exists_but_wip_does_not_link_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            SessionRecoveryTests.attach_current_model(brain)
            self._write_sources_fixture(
                brain,
                wip_body="# WIP\n\n## Some project\n- unrelated dashboard entry, no source link\n",
            )

            result = self._run_session_open(brain, "session-sources-dormant", "/workspace/runtime-project")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("sources_due:", result.stdout)

    def test_bare_prose_mention_of_the_registry_filename_does_not_activate(self) -> None:
        # A textual mention of the filename, with no real wikilink or markdown link,
        # must not activate -- this is the fix for the cross-project activation leak
        # (a real link is required, not a substring match over prose).
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            SessionRecoveryTests.attach_current_model(brain)
            self._write_sources_fixture(
                brain,
                wip_body="# WIP\n\n## Some project\n- We considered sources.registry.md once.\n",
            )

            result = self._run_session_open(brain, "session-sources-prose-only", "/workspace/runtime-project")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("sources_due:", result.stdout)

    def test_dry_run_surfaces_blocked_source_distinctly_from_due(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            SessionRecoveryTests.attach_current_model(brain)
            self._write_sources_fixture(
                brain,
                wip_body="# WIP\n\n## Fuentes externas\n\n- [[sources.registry|registry]]\n",
            )
            # Break the descriptor's capability so it resolves to blocked, not due.
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"
            descriptor.write_text(
                descriptor.read_text(encoding="utf-8").replace(
                    "Requires capability: chat.search", "Requires capability: issues.search"
                ),
                encoding="utf-8",
            )

            result = self._run_session_open(brain, "session-sources-blocked", "/workspace/runtime-project")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sources_due:", result.stdout)
        self.assertIn("- slack-eng: blocked —", result.stdout)

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

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from tests.support.session_open_test_support import SCRIPTS_DIR  # noqa: F401  (sys.path side effect)

import maintenance_scheduler as ms  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


class ContainsCurrentPeriodTests(unittest.TestCase):
    def test_incidental_date_in_refs_does_not_fake_current_week(self) -> None:
        # Given: a Weekly entry that is structurally stale (period 2026-W23) whose
        # `refs:` wikilink happens to name `today`.
        today = date(2026, 8, 20)
        lines = [
            "- run: 2026-06-03",
            "  run_at: 2026-06-03T13:40:44+02:00",
            "  period: 2026-W23",
            "  status: done",
            "  summary: stale entry",
            f"  refs: [[{today.isoformat()}]]",
        ]

        # When / Then: the incidental date must not make the job look current.
        self.assertFalse(ms.contains_current_week(lines, today))

    def test_incidental_date_in_run_at_does_not_fake_current_month(self) -> None:
        # Given: a Monthly entry stale by period, but run_at happens to be this month.
        today = date(2026, 8, 20)
        lines = [
            "- run: 2026-06-03",
            f"  run_at: {today.isoformat()}T10:00:00+02:00",
            "  period: 2026-06",
            "  status: done",
            "  summary: stale entry",
        ]

        self.assertFalse(ms.contains_current_month(lines, today))

    def test_structured_entry_for_current_week_is_recognized(self) -> None:
        # Given: a genuinely current, structured, done entry.
        today = date(2026, 8, 20)
        current_week = f"{today.isocalendar().year}-W{today.isocalendar().week:02d}"
        lines = [
            f"- run: {today.isoformat()}",
            f"  period: {current_week}",
            "  status: done",
            "  summary: ran this week",
        ]

        self.assertTrue(ms.contains_current_week(lines, today))

    def test_structured_entry_for_current_month_is_recognized(self) -> None:
        today = date(2026, 8, 20)
        current_month = f"{today.year}-{today.month:02d}"
        lines = [
            f"- run: {today.isoformat()}",
            f"  period: {current_month}",
            "  status: done",
            "  summary: ran this month",
        ]

        self.assertTrue(ms.contains_current_month(lines, today))


class DecideJobsTests(unittest.TestCase):
    def test_missing_jobs_log_reports_all_calendar_jobs_due(self) -> None:
        # Given: a brain with no JOBS_LOGS.md at all. This is existing fail-open-
        # into-due behavior and is intentionally left unchanged by this fix.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            decisions = ms.decide_jobs(brain, date(2026, 8, 20))

        by_name = {d.name: d.status for d in decisions}
        self.assertEqual(by_name["Weekly"], "due")
        self.assertEqual(by_name["Monthly"], "due")
        self.assertEqual(by_name["Yearly"], "due")


class SummarizeDueJobsTests(unittest.TestCase):
    def test_excludes_daily_and_session_consolidation(self) -> None:
        # Given: a fresh brain (Daily and Session consolidation would otherwise
        # always be reportable — Daily via the digest's own fields, Session
        # consolidation because decide_jobs() always marks it "review").
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            summary = ms.summarize_due_jobs(brain, date(2026, 8, 20))

        joined = "\n".join(summary)
        self.assertNotIn("Daily", joined)
        self.assertNotIn("Session consolidation", joined)
        self.assertTrue(any(line.startswith("- Weekly:") for line in summary))
        self.assertTrue(any(line.startswith("- Monthly:") for line in summary))
        self.assertTrue(any(line.startswith("- Yearly:") for line in summary))

    def test_omits_weekly_once_logged_for_the_current_week(self) -> None:
        # Given: Weekly already logged for the current ISO week.
        today = date(2026, 8, 20)
        current_week = f"{today.isocalendar().year}-W{today.isocalendar().week:02d}"
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "JOBS_LOGS.md",
                "## Weekly\n"
                f"- run: {today.isoformat()}\n"
                f"  period: {current_week}\n"
                "  status: done\n"
                "  summary: done this week\n",
            )
            summary = ms.summarize_due_jobs(brain, today)

        self.assertFalse(any(line.startswith("- Weekly") for line in summary))

    def test_includes_yearly_in_progress_as_review(self) -> None:
        today = date(2026, 8, 20)
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "JOBS_LOGS.md",
                "## Yearly\n"
                f"- run: {today.isoformat()}\n"
                f"  period: {today.year}\n"
                "  status: in_progress\n"
                "  summary: archive underway\n",
            )
            summary = ms.summarize_due_jobs(brain, today)

        self.assertTrue(any(line.startswith("- Yearly: review") for line in summary))


if __name__ == "__main__":
    unittest.main()

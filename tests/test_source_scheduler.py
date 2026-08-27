from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from tests.support.session_open_test_support import SCRIPTS_DIR  # noqa: F401  (sys.path side effect)

import source_scheduler as ss  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _registry(*entries: str) -> str:
    return "# Source registry\n\n## Sources\n\n" + "\n".join(entries)


def _entry(slug: str, status: str, source_type: str = "messaging-tool") -> str:
    return f"### {slug}\n- Status: {status}\n- Type: {source_type}\n\n"


class RegistryParsingTests(unittest.TestCase):
    def test_only_enabled_sources_are_returned(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            registry = brain / "WIP" / "SOURCES" / "sources.registry.md"
            _write(
                registry,
                _registry(
                    _entry("slack-eng", "enabled"),
                    _entry("old-tool", "disabled"),
                ),
            )
            entries = ss.enabled_sources(registry)

        self.assertEqual([e.slug for e in entries], ["slack-eng"])

    def test_missing_registry_returns_no_sources(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            entries = ss.enabled_sources(brain / "WIP" / "SOURCES" / "sources.registry.md")

        self.assertEqual(entries, [])


class DecideDueTests(unittest.TestCase):
    def test_never_checked_is_due(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            _write(descriptor, "# Source: slack-eng\n\n## Schedule\n- Last checked: not checked\n")

            decision = ss.decide_due(descriptor, date(2026, 8, 27), "slack-eng")

        self.assertTrue(decision.due)
        self.assertEqual(decision.reason, "never checked")

    def test_checked_today_with_default_cadence_is_not_due(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            _write(
                descriptor,
                "# Source: slack-eng\n\n## Schedule\n- Last checked: 2026-08-27\n",
            )

            decision = ss.decide_due(descriptor, date(2026, 8, 27), "slack-eng")

        self.assertFalse(decision.due)

    def test_checked_before_cadence_window_is_due(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.weekly-tool.md"
            _write(
                descriptor,
                "# Source: weekly-tool\n\n## Schedule\n"
                "- Check cadence (days): 7\n"
                "- Last checked: 2026-08-01\n",
            )

            not_yet = ss.decide_due(descriptor, date(2026, 8, 7), "weekly-tool")
            now_due = ss.decide_due(descriptor, date(2026, 8, 8), "weekly-tool")

        self.assertFalse(not_yet.due)
        self.assertTrue(now_due.due)

    def test_missing_descriptor_is_due(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.ghost.md"

            decision = ss.decide_due(descriptor, date(2026, 8, 27), "ghost")

        self.assertTrue(decision.due)
        self.assertEqual(decision.reason, "never checked")

    def test_always_cadence_is_always_due_even_when_checked_today(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.calendar.md"
            _write(
                descriptor,
                "# Source: calendar\n\n## Schedule\n"
                "- Check cadence (days): always\n"
                "- Last checked: 2026-08-27\n",
            )

            decision = ss.decide_due(descriptor, date(2026, 8, 27), "calendar")

        self.assertTrue(decision.due)
        self.assertEqual(decision.reason, "always due (cadence: always)")


class SummarizeDueSourcesTests(unittest.TestCase):
    def test_disabled_source_is_excluded_even_when_never_checked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            registry = brain / "WIP" / "SOURCES" / "sources.registry.md"
            _write(registry, _registry(_entry("old-tool", "disabled")))

            summary = ss.summarize_due_sources(brain, date(2026, 8, 27))

        self.assertEqual(summary, [])

    def test_enabled_and_due_source_is_listed_with_type(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            registry = brain / "WIP" / "SOURCES" / "sources.registry.md"
            _write(registry, _registry(_entry("slack-eng", "enabled", "messaging-tool")))

            summary = ss.summarize_due_sources(brain, date(2026, 8, 27))

        self.assertEqual(len(summary), 1)
        self.assertTrue(summary[0].startswith("- slack-eng (messaging-tool):"))


class MarkCheckedTests(unittest.TestCase):
    def test_round_trip_updates_both_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            _write(
                descriptor,
                "# Source: slack-eng\n\n## Schedule\n"
                "- Check cadence (days): 1\n"
                "- Last checked: not checked\n"
                "- Last status: not checked\n",
            )

            ss.mark_checked(descriptor, date(2026, 8, 27), "ok")
            updated = descriptor.read_text(encoding="utf-8")

        self.assertIn("- Last checked: 2026-08-27", updated)
        self.assertIn("- Last status: ok", updated)

    def test_invalid_status_is_rejected_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            original = (
                "# Source: slack-eng\n\n## Schedule\n"
                "- Last checked: not checked\n- Last status: not checked\n"
            )
            _write(descriptor, original)

            with self.assertRaises(ValueError):
                ss.mark_checked(descriptor, date(2026, 8, 27), "bogus")

            self.assertEqual(descriptor.read_text(encoding="utf-8"), original)

    def test_missing_descriptor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.ghost.md"
            with self.assertRaises(FileNotFoundError):
                ss.mark_checked(descriptor, date(2026, 8, 27), "ok")

    def test_descriptor_missing_fields_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            _write(descriptor, "# Source: slack-eng\n\nNo schedule fields here.\n")

            with self.assertRaises(ValueError):
                ss.mark_checked(descriptor, date(2026, 8, 27), "ok")


if __name__ == "__main__":
    unittest.main()

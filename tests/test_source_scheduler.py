from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tests.support.session_open_test_support import SCRIPTS_DIR

import source_scheduler as ss  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _registry(*entries: str) -> str:
    return "# Source registry\n\n## Sources\n\n" + "\n".join(entries)


def _entry(slug: str, status: str, source_type: str = "messaging-tool") -> str:
    return f"### {slug}\n- Status: {status}\n- Type: {source_type}\n\n"


def _write_profile(brain: Path, capability: str = "chat.search") -> None:
    """A minimal, schema-valid environment profile that routes `capability`."""
    _write(
        brain / "_AGENTS" / "SHARED" / "environment.json",
        json.dumps({"schema_version": 1, "default_profile": "test", "project_rules": []}),
    )
    _write(
        brain / "_AGENTS" / "SHARED" / "profiles" / "test.json",
        json.dumps(
            {
                "schema_version": 1,
                "id": "test",
                "display_name": "Test",
                "providers": {
                    "manual-tool": {
                        "kind": "manual",
                        "service": "manual-tool",
                        "required": False,
                        "operations": {},
                    }
                },
                "capability_routes": {capability: ["manual-tool"]},
                "projects": [],
            }
        ),
    )


def _write_guide(brain: Path, source_type: str = "messaging-tool") -> None:
    _write(brain / "SOURCE_TYPES" / f"{source_type}.md", f"# {source_type}\n")


def _descriptor(
    *,
    capability: str = "chat.search",
    locator: str = "#eng channel",
    cadence: str = "1",
    last_checked: str = "not checked",
    last_status: str = "not checked",
) -> str:
    return (
        "# Source: slack-eng\n\n"
        "## Access\n\n"
        f"- Requires capability: {capability}\n"
        f"- Locator: {locator}\n\n"
        "## Schedule\n\n"
        f"- Check cadence (days): {cadence}\n"
        f"- Last checked: {last_checked}\n"
        f"- Last status: {last_status}\n"
    )


def _build_working_brain(raw: str, **descriptor_kwargs) -> Path:
    """A brain with one enabled, fully-resolvable source: registry + descriptor +
    guide + environment profile all present and consistent. Individual tests mutate
    one piece of this to exercise a specific blocked/due/not-due path."""
    brain = Path(raw)
    _write(
        brain / "WIP" / "SOURCES" / "sources.registry.md",
        _registry(_entry("slack-eng", "enabled", "messaging-tool")),
    )
    _write(brain / "WIP" / "SOURCES" / "sources.slack-eng.md", _descriptor(**descriptor_kwargs))
    _write_guide(brain)
    _write_profile(brain)
    return brain


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


class RegistryActivatedTests(unittest.TestCase):
    def test_no_wip_md_is_dormant(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            self.assertFalse(ss.registry_activated(Path(raw)))

    def test_wikilink_anywhere_in_wip_activates_regardless_of_heading(self) -> None:
        # Brain-scoped: no per-project heading match, no cwd filter. Any heading the
        # user chooses is fine.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(brain / "WIP" / "WIP.md", "## Fuentes externas\n\n- [[sources.registry|registry]]\n")
            self.assertTrue(ss.registry_activated(brain))

    def test_markdown_link_activates(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(brain / "WIP" / "WIP.md", "## Anything\n\n- [registry](WIP/SOURCES/sources.registry.md)\n")
            self.assertTrue(ss.registry_activated(brain))

    def test_bare_prose_mention_does_not_activate(self) -> None:
        # A textual mention of the filename, with no real link, must not activate --
        # this is the fix for the "fuga entre proyectos" finding: prose is not a link.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "WIP.md",
                "## Some project\n\n- We considered using sources.registry.md once.\n",
            )
            self.assertFalse(ss.registry_activated(brain))

    def test_unrelated_heading_with_no_link_does_not_activate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(brain / "WIP" / "WIP.md", "## Unrelated project\n\n- nothing to see here\n")
            self.assertFalse(ss.registry_activated(brain))


class DecideSourceBlockedTests(unittest.TestCase):
    def _decide(self, brain: Path, today: date = date(2026, 8, 27)) -> ss.SourceDecision:
        decisions = ss.decide_sources(brain, today)
        self.assertEqual(len(decisions), 1)
        return decisions[0]

    def test_fully_resolvable_source_is_due_never_checked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            decision = self._decide(brain)

        self.assertFalse(decision.blocked)
        self.assertTrue(decision.due)
        self.assertEqual(decision.reason, "never checked")

    def test_missing_descriptor_is_blocked_not_due(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(_entry("slack-eng", "enabled")),
            )
            _write_guide(brain)
            _write_profile(brain)
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertFalse(decision.due)
        self.assertIn("not found", decision.reason)

    def test_symlinked_descriptor_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            outside = Path(raw).parent / "outside-descriptor.md"
            _write(outside, _descriptor())
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"
            descriptor.unlink()
            descriptor.symlink_to(outside)
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("symlink", decision.reason)

    def test_missing_source_type_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(_entry("slack-eng", "enabled", source_type="")),
            )
            _write(brain / "WIP" / "SOURCES" / "sources.slack-eng.md", _descriptor())
            _write_profile(brain)
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("missing source type", decision.reason)

    def test_unwritten_source_type_guide_is_blocked(self) -> None:
        # Covers the review-requests stub: a type with no SOURCE_TYPES guide yet must
        # never be investigated (RULES-OPTIONAL-CAPABILITIES.common.md).
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(_entry("review-requests", "enabled", source_type="review-requests")),
            )
            _write(brain / "WIP" / "SOURCES" / "sources.review-requests.md", _descriptor())
            _write_profile(brain)
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("no guide for type", decision.reason)

    def test_missing_capability_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw, capability="")
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("Requires capability", decision.reason)

    def test_malformed_capability_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw, capability="Not Valid!")
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("Requires capability", decision.reason)

    def test_capability_not_routed_by_profile_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw, capability="issues.search")
            decision = self._decide(brain)  # profile only routes chat.search

        self.assertTrue(decision.blocked)
        self.assertIn("not routed", decision.reason)

    def test_no_environment_profile_configured_blocks_every_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(_entry("slack-eng", "enabled")),
            )
            _write(brain / "WIP" / "SOURCES" / "sources.slack-eng.md", _descriptor())
            _write_guide(brain)
            # deliberately no _AGENTS/SHARED profile documents
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("no usable environment profile", decision.reason)

    def test_missing_cadence_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw, cadence="")
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("cadence", decision.reason)

    def test_non_numeric_cadence_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw, cadence="often")
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("invalid cadence", decision.reason)

    def test_zero_or_negative_cadence_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw, cadence="0")
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("invalid cadence", decision.reason)

    def test_missing_last_checked_field_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"
            text = descriptor.read_text(encoding="utf-8")
            descriptor.write_text(
                "\n".join(line for line in text.splitlines() if "Last checked" not in line) + "\n",
                encoding="utf-8",
            )
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("Last checked", decision.reason)

    def test_invalid_last_checked_date_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw, last_checked="whenever")
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("invalid 'Last checked'", decision.reason)

    def test_never_checked_sentinels_are_due(self) -> None:
        for sentinel in ("not checked", "none", ""):
            with self.subTest(sentinel=sentinel):
                with tempfile.TemporaryDirectory() as raw:
                    brain = _build_working_brain(raw, last_checked=sentinel)
                    decision = self._decide(brain)
                self.assertFalse(decision.blocked)
                self.assertTrue(decision.due)


class DecideSourceCadenceTests(unittest.TestCase):
    def _due(self, raw: str, last_checked: str, cadence: str, today: date) -> bool:
        brain = _build_working_brain(raw, cadence=cadence, last_checked=last_checked)
        decisions = ss.decide_sources(brain, today)
        self.assertFalse(decisions[0].blocked, decisions[0].reason)
        return decisions[0].due

    def test_checked_before_cadence_window_is_due(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            not_yet = self._due(raw, "2026-08-01", "7", date(2026, 8, 7))
        with tempfile.TemporaryDirectory() as raw:
            now_due = self._due(raw, "2026-08-01", "7", date(2026, 8, 8))
        self.assertFalse(not_yet)
        self.assertTrue(now_due)

    def test_leap_day_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            not_yet = self._due(raw, "2028-02-28", "1", date(2028, 2, 28))
        with tempfile.TemporaryDirectory() as raw:
            now_due = self._due(raw, "2028-02-28", "1", date(2028, 2, 29))
        self.assertFalse(not_yet)
        self.assertTrue(now_due)

    def test_year_rollover_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            not_yet = self._due(raw, "2026-12-31", "1", date(2026, 12, 31))
        with tempfile.TemporaryDirectory() as raw:
            now_due = self._due(raw, "2026-12-31", "1", date(2027, 1, 1))
        self.assertFalse(not_yet)
        self.assertTrue(now_due)

    def test_always_cadence_is_always_due_even_when_checked_today(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw, cadence="always", last_checked="2026-08-27")
            decision = ss.decide_sources(brain, date(2026, 8, 27))[0]

        self.assertFalse(decision.blocked)
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
            brain = _build_working_brain(raw)
            summary = ss.summarize_due_sources(brain, date(2026, 8, 27))

        self.assertEqual(len(summary), 1)
        self.assertTrue(summary[0].startswith("- slack-eng (messaging-tool):"))

    def test_blocked_source_is_listed_distinctly_from_due(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw, capability="issues.search")
            summary = ss.summarize_due_sources(brain, date(2026, 8, 27))

        self.assertEqual(len(summary), 1)
        self.assertTrue(summary[0].startswith("- slack-eng: blocked —"))

    def test_always_source_and_not_due_numeric_source_only_surface_the_always_one(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(
                    _entry("calendar-personal", "enabled", "calendar"),
                    _entry("slack-eng", "enabled", "messaging-tool"),
                ),
            )
            _write(
                brain / "WIP" / "SOURCES" / "sources.calendar-personal.md",
                _descriptor(cadence="always", last_checked="2026-08-27"),
            )
            _write(
                brain / "WIP" / "SOURCES" / "sources.slack-eng.md",
                _descriptor(cadence="7", last_checked="2026-08-27"),
            )
            _write_guide(brain, "calendar")
            _write_guide(brain, "messaging-tool")
            _write_profile(brain)

            summary = ss.summarize_due_sources(brain, date(2026, 8, 27))

        self.assertEqual(len(summary), 1)
        self.assertTrue(summary[0].startswith("- calendar-personal"))


class MarkCheckedTests(unittest.TestCase):
    def test_round_trip_updates_both_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            _write(descriptor, _descriptor())

            ss.mark_checked(descriptor, date(2026, 8, 27), "ok")
            updated = descriptor.read_text(encoding="utf-8")

        self.assertIn("- Last checked: 2026-08-27", updated)
        self.assertIn("- Last status: ok", updated)

    def test_degraded_leaves_last_checked_untouched_but_records_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            _write(descriptor, _descriptor(last_checked="2026-08-01"))

            ss.mark_checked(descriptor, date(2026, 8, 27), "degraded")
            updated = descriptor.read_text(encoding="utf-8")

        self.assertIn("- Last checked: 2026-08-01", updated)
        self.assertIn("- Last status: degraded", updated)

    def test_degraded_does_not_create_an_unread_gap_on_next_success(self) -> None:
        # End-to-end version of the above: a degraded attempt on day 20 must leave the
        # source still due on day 20 (no window silently skipped), and a subsequent
        # `ok` on day 27 is the one that finally advances the watermark to day 27, not
        # some later date that would imply days 1-27 were read when they weren't.
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw, cadence="7", last_checked="2026-08-01")
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"

            ss.mark_checked(descriptor, date(2026, 8, 20), "degraded")
            still_due = ss.decide_sources(brain, date(2026, 8, 20))[0]
            self.assertTrue(still_due.due)
            self.assertIn("2026-08-01", descriptor.read_text(encoding="utf-8"))

            ss.mark_checked(descriptor, date(2026, 8, 27), "ok")
            now_not_due = ss.decide_sources(brain, date(2026, 8, 27))[0]
            self.assertFalse(now_not_due.due)
            self.assertIn("- Last checked: 2026-08-27", descriptor.read_text(encoding="utf-8"))

    def test_invalid_status_is_rejected_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            original = _descriptor()
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

    def test_symlinked_descriptor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            outside = Path(raw) / "outside.md"
            _write(outside, _descriptor())
            descriptor = Path(raw) / "sources.slack-eng.md"
            descriptor.symlink_to(outside)

            with self.assertRaises(ValueError):
                ss.mark_checked(descriptor, date(2026, 8, 27), "ok")

            self.assertNotIn("2026-08-27", outside.read_text(encoding="utf-8"))


class DescriptorPathForTests(unittest.TestCase):
    def test_valid_slug_resolves(self) -> None:
        path = ss.descriptor_path_for(Path("/brain/WIP/SOURCES"), "slack-eng")
        self.assertEqual(path, Path("/brain/WIP/SOURCES/sources.slack-eng.md"))

    def test_traversal_slug_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ss.descriptor_path_for(Path("/brain/WIP/SOURCES"), "../../etc/passwd")

    def test_slug_with_slash_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ss.descriptor_path_for(Path("/brain/WIP/SOURCES"), "a/b")


class ParseArgsTests(unittest.TestCase):
    def test_documented_skill_argument_order_parses(self) -> None:
        # The exact form documented in SKILL.md: --brain-root after the subcommand.
        args = ss.parse_args(
            ["mark-checked", "--brain-root", "/tmp/brain", "--source", "x", "--status", "ok"]
        )
        self.assertEqual(args.brain_root, "/tmp/brain")
        self.assertEqual(args.command, "mark-checked")

    def test_brain_root_before_subcommand_also_parses(self) -> None:
        args = ss.parse_args(
            ["--brain-root", "/tmp/brain", "mark-checked", "--source", "x", "--status", "ok"]
        )
        self.assertEqual(args.brain_root, "/tmp/brain")

    def test_apply_flag_defaults_false_and_is_captured_when_present(self) -> None:
        without = ss.parse_args(["mark-checked", "--source", "x", "--status", "ok"])
        with_apply = ss.parse_args(["mark-checked", "--source", "x", "--status", "ok", "--apply"])
        self.assertFalse(without.apply)
        self.assertTrue(with_apply.apply)


class MarkCheckedCliTests(unittest.TestCase):
    """CLI-level tests: exercise main() via subprocess, the actual published contract,
    not just the internal mark_checked() function."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "source_scheduler.py"), *args],
            text=True, capture_output=True, check=False,
        )

    def test_documented_form_parses_and_dry_runs_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"
            before = descriptor.read_text(encoding="utf-8")

            result = self._run(
                "mark-checked", "--brain-root", str(brain),
                "--source", "slack-eng", "--status", "ok", "--date", "2026-08-27",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("dry-run", result.stdout)
            self.assertEqual(descriptor.read_text(encoding="utf-8"), before)

    def test_apply_writes_once_and_is_idempotent_on_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"

            first = self._run(
                "mark-checked", "--brain-root", str(brain),
                "--source", "slack-eng", "--status", "ok", "--date", "2026-08-27", "--apply",
            )
            after_first = descriptor.read_text(encoding="utf-8")
            second = self._run(
                "mark-checked", "--brain-root", str(brain),
                "--source", "slack-eng", "--status", "ok", "--date", "2026-08-27", "--apply",
            )
            after_second = descriptor.read_text(encoding="utf-8")

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(after_first, after_second)
            self.assertIn("- Last checked: 2026-08-27", after_first)
            # cleanup the log this run writes next to the script
            (SCRIPTS_DIR / "source_scheduler.log").unlink(missing_ok=True)

    def test_traversal_slug_is_rejected_without_touching_anything_outside(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            result = self._run(
                "mark-checked", "--brain-root", str(brain),
                "--source", "../../etc/passwd", "--status", "ok", "--apply",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("invalid source slug", result.stdout)
            (SCRIPTS_DIR / "source_scheduler.log").unlink(missing_ok=True)

    def test_symlinked_descriptor_is_rejected_by_cli(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            outside = Path(raw) / "outside.md"
            _write(outside, _descriptor())
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"
            descriptor.unlink()
            descriptor.symlink_to(outside)

            result = self._run(
                "mark-checked", "--brain-root", str(brain),
                "--source", "slack-eng", "--status", "ok", "--apply",
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("symlink", result.stdout)
            self.assertNotIn("2026", outside.read_text(encoding="utf-8"))
            (SCRIPTS_DIR / "source_scheduler.log").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

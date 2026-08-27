from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from tests.support.session_open_test_support import SCRIPTS_DIR

import source_scheduler as ss  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _registry(*entries: str) -> str:
    return "# Source registry\n\n## Sources\n\n" + "\n".join(entries)


def _entry(
    slug: str,
    status: str,
    source_type: str = "messaging-tool",
    *,
    descriptor: str | None = None,
) -> str:
    descriptor = f"[[sources.{slug}]]" if descriptor is None else descriptor
    return (
        f"### {slug}\n- Status: {status}\n- Type: {source_type}\n"
        f"- Descriptor: {descriptor}\n\n"
    )


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
        # Fifth-round review's `enabled_sources()` helper is gone (sixth-round
        # finding: it read via plain Path.exists()/read_text(), bypassing the
        # no-follow invariant every other read in this module honors, and had no
        # production caller to justify keeping an unsafe public entrypoint around).
        # This exercises the same "enabled-only filtering" behavior directly
        # against parse_registry_entries(), which is what any real caller uses.
        text = _registry(
            _entry("slack-eng", "enabled"),
            _entry("old-tool", "disabled"),
        )
        entries = [e for e in ss.parse_registry_entries(text) if e.status == "enabled"]

        self.assertEqual([e.slug for e in entries], ["slack-eng"])


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

    def test_near_name_wikilink_does_not_activate(self) -> None:
        # Second-round review finding: a raw substring match would fire on any target
        # that merely CONTAINS "sources.registry" as text, not just the exact file.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(brain / "WIP" / "WIP.md", "## Anything\n\n- [[not-sources.registry.md]]\n")
            self.assertFalse(ss.registry_activated(brain))

    def test_backup_wikilink_does_not_activate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(brain / "WIP" / "WIP.md", "## Anything\n\n- [[sources.registry.backup]]\n")
            self.assertFalse(ss.registry_activated(brain))

    def test_markdown_link_with_fragment_still_activates(self) -> None:
        # A real link to the registry with a heading fragment must not be rejected
        # just because something follows the ".md" before the closing paren.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "WIP.md",
                "## Anything\n\n- [registry](WIP/SOURCES/sources.registry.md#Sources)\n",
            )
            self.assertTrue(ss.registry_activated(brain))

    def test_link_inside_html_comment_does_not_activate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "WIP.md",
                "## Anything\n\n<!-- example: [[sources.registry]] -->\n",
            )
            self.assertFalse(ss.registry_activated(brain))

    def test_link_inside_fenced_code_does_not_activate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "WIP.md",
                "## Anything\n\n```\n[[sources.registry]]\n```\n",
            )
            self.assertFalse(ss.registry_activated(brain))

    def test_link_inside_inline_code_does_not_activate(self) -> None:
        # Third-round review finding: a single-backtick example (rendered as text by
        # Obsidian, not a link) still activated.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "WIP.md",
                "## Anything\n\nExample: `[[sources.registry]]`\n",
            )
            self.assertFalse(ss.registry_activated(brain))

    def test_external_url_ending_in_the_registry_filename_does_not_activate(self) -> None:
        # Third-round review finding: an absolute URL whose path happens to end in
        # sources.registry.md is not a local dashboard link.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "WIP.md",
                "## Anything\n\n[artifact](https://example.invalid/sources.registry.md)\n",
            )
            self.assertFalse(ss.registry_activated(brain))

    def test_protocol_relative_url_does_not_activate(self) -> None:
        # Fourth-round review finding: a scheme-less "//host/path" destination is
        # still an external reference, not a local link, and was previously missed
        # because only a full "scheme://" prefix was excluded.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "WIP.md",
                "## Anything\n\n[artifact](//example.invalid/sources.registry.md)\n",
            )
            self.assertFalse(ss.registry_activated(brain))

    def test_double_backtick_inline_code_does_not_activate(self) -> None:
        # Fourth-round review finding: INLINE_CODE_RE only matched single backticks,
        # so a double-backtick span (needed when the content itself contains a
        # backtick, or just used stylistically) was not stripped and still activated.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(brain / "WIP" / "WIP.md", "## Anything\n\n``[[sources.registry]]``\n")
            self.assertFalse(ss.registry_activated(brain))

    def test_tilde_fenced_code_does_not_activate(self) -> None:
        # Fourth-round review finding: a fenced code block may use tildes instead of
        # backticks; FENCED_CODE_RE previously only recognized backtick fences.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(brain / "WIP" / "WIP.md", "## Anything\n\n~~~\n[[sources.registry]]\n~~~\n")
            self.assertFalse(ss.registry_activated(brain))

    def test_unclosed_fenced_code_does_not_activate(self) -> None:
        # Fourth-round review finding: a fence with no closing run is implicitly
        # closed at EOF per CommonMark; the old regex required an explicit closing
        # fence and so treated an unclosed block as ordinary (activating) text.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(brain / "WIP" / "WIP.md", "## Anything\n\n```\n[[sources.registry]]\n")
            self.assertFalse(ss.registry_activated(brain))

    def test_angle_bracket_link_destination_activates(self) -> None:
        # Fourth-round review finding: CommonMark allows wrapping a link destination
        # in <...>; the old parser compared the literal "<WIP/SOURCES/..." string as
        # a basename and never matched, rejecting a valid local link.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "WIP.md",
                "## Anything\n\n[registry](<WIP/SOURCES/sources.registry.md>)\n",
            )
            self.assertTrue(ss.registry_activated(brain))

    def test_angle_bracketed_external_url_does_not_activate(self) -> None:
        # Fifth-round review finding: the external/protocol-relative check ran on
        # the still-<...>-bracketed destination, which matches neither
        # URL_SCHEME_RE nor PROTOCOL_RELATIVE_RE (both anchor on the first
        # character, here "<"). Unwrapping happened only afterward, so the
        # destination was reclassified as local and activated.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "WIP.md",
                "## Anything\n\n[artifact](<https://example.invalid/sources.registry.md>)\n",
            )
            self.assertFalse(ss.registry_activated(brain))

    def test_non_closing_fence_line_does_not_end_the_fence_early(self) -> None:
        # Fifth-round review finding: the fence-closing pattern matched any line
        # that merely STARTED with the opening delimiter run, even with other
        # content after it (e.g. a longer run, or trailing text) -- not a valid
        # CommonMark close. A link genuinely still inside the fence could leak out
        # and activate.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "WIP.md",
                "## Anything\n\n```\nsome prefix\n```extra\n[[sources.registry]]\n```\n",
            )
            self.assertFalse(ss.registry_activated(brain))

    def test_titled_local_markdown_link_activates(self) -> None:
        # Fifth-round review finding: the destination regex captured everything up
        # to the first ")" or "#", so a link with a CommonMark title
        # (`[x](y.md "Title")`) had the title text folded into the "destination",
        # which then never matched the registry's basename -- rejecting a valid,
        # rendered local link.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "WIP.md",
                '## Anything\n\n[registry](WIP/SOURCES/sources.registry.md "Registry")\n',
            )
            self.assertTrue(ss.registry_activated(brain))

    def test_link_inside_an_unclosed_html_comment_does_not_activate(self) -> None:
        # Sixth-round review finding: HTML_COMMENT_RE only stripped CLOSED
        # comments. Under CommonMark, an "<!--" with no matching "-->" continues as
        # raw, unrendered HTML through end of document; a Markdown-looking link
        # inside it is not a real link, but the old regex left it in place for the
        # extractor to pick up.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(brain / "WIP" / "WIP.md", "<!-- [registry](WIP/SOURCES/sources.registry.md)\n")
            self.assertFalse(ss.registry_activated(brain))

    def test_closed_html_comment_is_still_stripped(self) -> None:
        # Guards the case above: an unclosed comment must run to EOF, but a
        # NORMAL, closed comment must still only strip its own span, not
        # everything after it.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "WIP.md",
                "<!-- [[sources.registry]] --> [registry](WIP/SOURCES/sources.registry.md)\n",
            )
            self.assertTrue(ss.registry_activated(brain))

    def test_uri_scheme_without_double_slash_does_not_activate(self) -> None:
        # Sixth-round review finding: URL_SCHEME_RE required a literal "scheme://",
        # but URI syntax doesn't require the "//" authority marker -- a rendered
        # destination like "https:/x" or "mailto:/x" still has a scheme and is not
        # a brain-relative path, yet slipped past a "://"-only check.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "WIP.md",
                "## Anything\n\n[registry](https:/sources.registry.md)\n",
            )
            self.assertFalse(ss.registry_activated(brain))

    def test_mismatched_backtick_run_lengths_do_not_hide_a_rendered_link(self) -> None:
        # Sixth-round review finding: INLINE_CODE_RE's bare backreference let a
        # short opening run (e.g. two backticks) match as a PREFIX of a longer,
        # unrelated closing run (e.g. the first two backticks of a later run of
        # three) even though CommonMark does not pair mismatched-length runs --
        # incorrectly treating a genuinely rendered link between them as code and
        # hiding it from activation.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "WIP.md",
                "## Anything\n\n`` [registry](WIP/SOURCES/sources.registry.md) ```\n",
            )
            self.assertTrue(ss.registry_activated(brain))

    def test_fifo_leaf_does_not_hang_registry_activated(self) -> None:
        # Fifth-round review finding: the leaf open used a plain blocking O_RDONLY,
        # so a FIFO with no writer blocked inside open() itself, well before the
        # S_ISREG check that would otherwise reject it -- hanging session start
        # indefinitely instead of yielding dormant. A SIGALRM bounds this test so a
        # regression fails fast instead of hanging the whole suite.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            (brain / "WIP").mkdir()
            os.mkfifo(brain / "WIP" / "WIP.md")

            def _timeout(signum, frame):
                raise TimeoutError("registry_activated() blocked on a FIFO leaf")

            old_handler = signal.signal(signal.SIGALRM, _timeout)
            signal.alarm(5)
            try:
                result = ss.registry_activated(brain)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

        self.assertFalse(result)


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
        self.assertIn("not safely readable", decision.reason)

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

    def test_missing_locator_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw, locator="")
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("Locator", decision.reason)

    def test_missing_last_status_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"
            # _descriptor() always writes the "- Last status:" line, even with an
            # empty value (which would still count as present); drop the whole line
            # to test true absence.
            text = descriptor.read_text(encoding="utf-8")
            descriptor.write_text(
                "\n".join(line for line in text.splitlines() if "Last status" not in line) + "\n",
                encoding="utf-8",
            )
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("Last status", decision.reason)

    def test_always_with_malformed_watermark_date_is_blocked(self) -> None:
        # Second-round review finding: the always-cadence branch returned early
        # without validating a non-sentinel Last checked value.
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw, cadence="always", last_checked="not-a-date")
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("invalid 'Last checked'", decision.reason)

    def test_duplicate_descriptor_field_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"
            text = descriptor.read_text(encoding="utf-8")
            descriptor.write_text(text + "- Last checked: 2026-08-02\n", encoding="utf-8")
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("duplicate field", decision.reason)
        self.assertIn("last checked", decision.reason)

    def test_invalid_utf8_descriptor_is_blocked_not_a_crash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"
            descriptor.write_bytes(b"\xff\xfe not valid utf-8")
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("UTF-8", decision.reason)

    def test_descriptor_field_missing_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(_entry("slack-eng", "enabled", "messaging-tool", descriptor="")),
            )
            _write(brain / "WIP" / "SOURCES" / "sources.slack-eng.md", _descriptor())
            _write_guide(brain)
            _write_profile(brain)
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("Descriptor", decision.reason)

    def test_descriptor_field_naming_a_different_slug_is_blocked(self) -> None:
        # Second-round review finding: the registry's Descriptor field was parsed
        # but never checked against the slug it was filed under.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(
                    _entry("slack-eng", "enabled", "messaging-tool", descriptor="[[sources.other]]")
                ),
            )
            _write(brain / "WIP" / "SOURCES" / "sources.slack-eng.md", _descriptor())
            _write(brain / "WIP" / "SOURCES" / "sources.other.md", _descriptor())
            _write_guide(brain)
            _write_profile(brain)
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("Descriptor", decision.reason)

    def test_descriptor_field_naming_the_expected_slug_plus_a_conflicting_one_is_blocked(self) -> None:
        # Sixth-round review finding: the cross-check passed if ANY extracted
        # target matched the expected slug, so a value naming both this slug and a
        # second, conflicting one (e.g. "[[sources.slug]] and
        # [[sources.other]]") passed validation -- not a redirect (the read still
        # uses the deterministic path), but a silent loss of exactly the
        # ambiguous/stale-metadata detection this cross-check exists to catch. The
        # documented contract (TEMPLATE.source-registry.common.md) is a single
        # wikilink naming this slug, nothing else.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(
                    _entry(
                        "slack-eng", "enabled", "messaging-tool",
                        descriptor="[[sources.slack-eng]] and [[sources.other]]",
                    )
                ),
            )
            _write(brain / "WIP" / "SOURCES" / "sources.slack-eng.md", _descriptor())
            _write_guide(brain)
            _write_profile(brain)
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("Descriptor", decision.reason)

    def test_source_type_path_traversal_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            outside_guide = Path(raw).parent / "outside-guide.md"
            _write(outside_guide, "# outside\n")
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(_entry("slack-eng", "enabled", "../../outside-guide")),
            )
            _write(brain / "WIP" / "SOURCES" / "sources.slack-eng.md", _descriptor())
            _write_profile(brain)
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("invalid source type", decision.reason)

    def test_symlinked_source_type_guide_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            outside_guide = Path(raw).parent / "outside-guide.md"
            _write(outside_guide, "# outside\n")
            guide = brain / "SOURCE_TYPES" / "messaging-tool.md"
            guide.unlink()
            guide.symlink_to(outside_guide)
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("not safely readable", decision.reason)

    def test_invalid_utf8_source_type_guide_is_blocked_not_dispatched(self) -> None:
        # Third-round review finding: the guide was only lstat'd for shape, never
        # actually read, so an unreadable guide the subagent can't deep-read was
        # still dispatched as due.
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            guide = brain / "SOURCE_TYPES" / "messaging-tool.md"
            guide.write_bytes(b"\xff\xfe not valid utf-8")
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("UTF-8", decision.reason)

    def test_unreadable_source_type_directory_is_blocked_not_a_crash(self) -> None:
        # Sixth-round review finding: a separate lstat_entry(guide_path).exists
        # preflight only distinguished "missing" via FileNotFoundError, so an
        # unreadable SOURCE_TYPES/ directory (e.g. mode 000) raised a bare
        # PermissionError instead of a blocked decision -- and since
        # collect_session_digest_state() doesn't catch scheduler exceptions, that
        # could abort session open entirely rather than surfacing one blocked
        # source.
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            source_types_dir = brain / "SOURCE_TYPES"
            source_types_dir.chmod(0o000)
            try:
                decision = self._decide(brain)
            finally:
                source_types_dir.chmod(0o755)

        self.assertTrue(decision.blocked)
        self.assertIn("not safely readable", decision.reason)

    def test_whitespace_only_source_type_guide_is_blocked(self) -> None:
        # Sixth-round review finding: the guide was verified readable but its text
        # was discarded unchecked, so a zero-byte or whitespace-only guide -- an
        # "unwritten" source type per the rule's own contract -- still let the
        # source through as due.
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            guide = brain / "SOURCE_TYPES" / "messaging-tool.md"
            guide.write_text("   \n\n  \n", encoding="utf-8")
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("empty", decision.reason)

    def test_directory_named_like_a_guide_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(_entry("slack-eng", "enabled", "messaging-tool")),
            )
            _write(brain / "WIP" / "SOURCES" / "sources.slack-eng.md", _descriptor())
            (brain / "SOURCE_TYPES" / "messaging-tool.md").mkdir(parents=True)
            _write_profile(brain)
            decision = self._decide(brain)

        self.assertTrue(decision.blocked)
        self.assertIn("not a regular file", decision.reason)


class RegistryLevelBlockedTests(unittest.TestCase):
    def test_missing_registry_is_blocked_when_activated(self) -> None:
        # Distinct from "registry exists with zero enabled entries," which is a
        # legitimate quiet result -- an activated capability whose registry is gone
        # must be visible, not silently empty.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            decisions = ss.decide_sources(brain, date(2026, 8, 27))

        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].blocked)
        self.assertIn("not found", decisions[0].reason)

    def test_symlinked_registry_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            outside_registry = Path(raw).parent / "outside-registry.md"
            _write(outside_registry, _registry(_entry("slack-eng", "enabled")))
            registry = brain / "WIP" / "SOURCES" / "sources.registry.md"
            registry.parent.mkdir(parents=True)
            registry.symlink_to(outside_registry)
            decisions = ss.decide_sources(brain, date(2026, 8, 27))

        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].blocked)
        self.assertIn("not safely readable", decisions[0].reason)

    def test_invalid_utf8_registry_is_blocked_not_a_crash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            registry = brain / "WIP" / "SOURCES" / "sources.registry.md"
            registry.parent.mkdir(parents=True)
            registry.write_bytes(b"\xff\xfe not valid utf-8")
            decisions = ss.decide_sources(brain, date(2026, 8, 27))

        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].blocked)
        self.assertIn("UTF-8", decisions[0].reason)

    def test_duplicate_enabled_slug_is_one_blocked_decision_not_two_dispatches(self) -> None:
        # Second-round review finding: a duplicate slug produced two separate
        # SourceDecisions (and so two subagent dispatches) instead of one ambiguity.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(
                    _entry("slack-eng", "enabled", "messaging-tool"),
                    _entry("slack-eng", "enabled", "messaging-tool"),
                ),
            )
            _write(brain / "WIP" / "SOURCES" / "sources.slack-eng.md", _descriptor())
            _write_guide(brain)
            _write_profile(brain)
            decisions = ss.decide_sources(brain, date(2026, 8, 27))

        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].blocked)
        self.assertIn("duplicate", decisions[0].reason)

    def test_enabled_and_disabled_sections_sharing_a_slug_is_blocked(self) -> None:
        # Third-round review finding: duplicates were computed only from the
        # already-`enabled`-filtered list, so one enabled + one disabled section for
        # the same slug slipped through as an unambiguous single source.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(
                    _entry("slack-eng", "enabled", "messaging-tool"),
                    _entry("slack-eng", "disabled", "messaging-tool"),
                ),
            )
            _write(brain / "WIP" / "SOURCES" / "sources.slack-eng.md", _descriptor())
            _write_guide(brain)
            _write_profile(brain)
            decisions = ss.decide_sources(brain, date(2026, 8, 27))

        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].blocked)
        self.assertIn("duplicate", decisions[0].reason)

    def test_disabled_and_disabled_sections_sharing_a_slug_is_blocked(self) -> None:
        # Fourth-round review finding: duplicate detection was computed across every
        # parsed entry, but the reporting loop only walked the `enabled`-filtered
        # list -- two `disabled` sections sharing a slug never reached the loop at
        # all, so the ambiguity was silently dropped instead of surfaced.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(
                    _entry("slack-eng", "disabled", "messaging-tool"),
                    _entry("slack-eng", "disabled", "messaging-tool"),
                ),
            )
            _write(brain / "WIP" / "SOURCES" / "sources.slack-eng.md", _descriptor())
            _write_guide(brain)
            _write_profile(brain)
            decisions = ss.decide_sources(brain, date(2026, 8, 27))

        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].blocked)
        self.assertIn("duplicate", decisions[0].reason)

    def test_duplicate_field_within_a_single_registry_entry_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(
                    "### slack-eng\n- Status: enabled\n- Type: messaging-tool\n"
                    "- Descriptor: [[sources.slack-eng]]\n"
                    "- Descriptor: [[sources.other]]\n\n"
                ),
            )
            _write(brain / "WIP" / "SOURCES" / "sources.slack-eng.md", _descriptor())
            _write_guide(brain)
            _write_profile(brain)
            decisions = ss.decide_sources(brain, date(2026, 8, 27))

        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].blocked)
        self.assertIn("duplicate field", decisions[0].reason)

    def test_duplicate_field_within_a_disabled_registry_entry_is_blocked(self) -> None:
        # Fifth-round review finding: duplicate_fields is computed for every parsed
        # entry, but was only ever reported from inside decide_source() -- which is
        # never called for a `disabled` entry. A single disabled section with two
        # `Descriptor:` lines produced no decision at all instead of a blocked one,
        # contradicting the settled contract that duplicate-field detection spans
        # every entry regardless of status (matching how duplicate slugs already do).
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(brain / "WIP" / "WIP.md", "## Anything\n\n- [[sources.registry]]\n")
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(
                    "### slack-eng\n- Status: disabled\n- Type: messaging-tool\n"
                    "- Descriptor: [[sources.slack-eng]]\n"
                    "- Descriptor: [[sources.other]]\n\n"
                ),
            )
            _write(brain / "WIP" / "SOURCES" / "sources.slack-eng.md", _descriptor())
            _write_guide(brain)
            _write_profile(brain)
            self.assertTrue(ss.registry_activated(brain))
            decisions = ss.decide_sources(brain, date(2026, 8, 27))

        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].blocked)
        self.assertIn("duplicate field", decisions[0].reason)

    def test_unreadable_registry_is_blocked_not_a_crash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            registry = brain / "WIP" / "SOURCES" / "sources.registry.md"
            _write(registry, _registry(_entry("slack-eng", "enabled")))
            registry.chmod(0o000)
            try:
                decisions = ss.decide_sources(brain, date(2026, 8, 27))
            finally:
                registry.chmod(0o644)

        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].blocked)
        self.assertIn("not safely readable", decisions[0].reason)

    def test_symlinked_parent_directory_of_the_registry_is_blocked_not_followed(self) -> None:
        # Fourth-round review finding: round-three's no-follow hardening only opened
        # the LEAF path component with O_NOFOLLOW; a symlink on a PARENT directory
        # component (here, WIP/SOURCES itself) was still followed, so the registry
        # read -- and, for mark-checked, the write -- could be silently redirected
        # into an attacker-controlled external directory. `_open_parent_no_follow()`
        # walks a directory-fd chain from `brain_root` so no parent component can be
        # swapped for a symlink without the walk itself refusing to follow it.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "brain"
            external = Path(raw) / "external-sources-dir"
            external.mkdir()
            _write(external / "sources.registry.md", _registry(_entry("slack-eng", "enabled")))
            (brain / "WIP").mkdir(parents=True)
            (brain / "WIP" / "SOURCES").symlink_to(external)

            decisions = ss.decide_sources(brain, date(2026, 8, 27))

        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].blocked)
        # A symlinked PARENT directory component fails the dir-fd chain's own
        # O_DIRECTORY|O_NOFOLLOW open with NotADirectoryError on this platform
        # (distinct from a symlinked LEAF file, which fails with ELOOP and surfaces
        # as "not safely readable") -- both are caught and reported, never followed.
        self.assertIn("not found", decisions[0].reason)


class SourceDecisionInvariantTests(unittest.TestCase):
    """`due` and `blocked` are meant to encode three exclusive states (due / not due /
    blocked), not four independent booleans. Lock that no code path can produce
    `due=True, blocked=True` together."""

    def test_due_and_blocked_are_never_both_true(self) -> None:
        cases: list[ss.SourceDecision] = []
        with tempfile.TemporaryDirectory() as raw:
            cases.append(self._decide_one(_build_working_brain(raw)))  # due
        with tempfile.TemporaryDirectory() as raw:
            cases.append(  # not due
                self._decide_one(_build_working_brain(raw, last_checked="2026-08-27"))
            )
        with tempfile.TemporaryDirectory() as raw:
            cases.append(self._decide_one(_build_working_brain(raw, locator="")))  # blocked

        for decision in cases:
            with self.subTest(decision=decision):
                self.assertFalse(decision.due and decision.blocked)

    @staticmethod
    def _decide_one(brain: Path) -> ss.SourceDecision:
        return ss.decide_sources(brain, date(2026, 8, 27))[0]


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

    def test_last_checked_near_date_max_plus_cadence_is_blocked_not_a_crash(self) -> None:
        # Fifth-round review finding: a syntactically valid but extreme 'Last
        # checked' date (date.fromisoformat accepts up to 9999-12-31) combined with
        # any positive cadence overflows date.max on addition; only ValueError from
        # parsing was handled, so the OverflowError escaped decide_source() entirely
        # instead of yielding a blocked decision for just that source.
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw, cadence="1", last_checked="9999-12-31")
            decisions = ss.decide_sources(brain, date(2026, 8, 28))

        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].blocked)
        self.assertIn("overflow", decisions[0].reason.lower())

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

            ss.mark_checked(descriptor, date(2026, 8, 27), "ok", Path(raw))
            updated = descriptor.read_text(encoding="utf-8")

        self.assertIn("- Last checked: 2026-08-27", updated)
        self.assertIn("- Last status: ok", updated)

    def test_degraded_leaves_last_checked_untouched_but_records_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            _write(descriptor, _descriptor(last_checked="2026-08-01"))

            ss.mark_checked(descriptor, date(2026, 8, 27), "degraded", Path(raw))
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

            ss.mark_checked(descriptor, date(2026, 8, 20), "degraded", brain)
            still_due = ss.decide_sources(brain, date(2026, 8, 20))[0]
            self.assertTrue(still_due.due)
            self.assertIn("2026-08-01", descriptor.read_text(encoding="utf-8"))

            ss.mark_checked(descriptor, date(2026, 8, 27), "ok", brain)
            now_not_due = ss.decide_sources(brain, date(2026, 8, 27))[0]
            self.assertFalse(now_not_due.due)
            self.assertIn("- Last checked: 2026-08-27", descriptor.read_text(encoding="utf-8"))

    def test_invalid_status_is_rejected_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            original = _descriptor()
            _write(descriptor, original)

            with self.assertRaises(ValueError):
                ss.mark_checked(descriptor, date(2026, 8, 27), "bogus", Path(raw))

            self.assertEqual(descriptor.read_text(encoding="utf-8"), original)

    def test_missing_descriptor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.ghost.md"
            with self.assertRaises(FileNotFoundError):
                ss.mark_checked(descriptor, date(2026, 8, 27), "ok", Path(raw))

    def test_descriptor_missing_fields_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            _write(descriptor, "# Source: slack-eng\n\nNo schedule fields here.\n")

            with self.assertRaises(ValueError):
                ss.mark_checked(descriptor, date(2026, 8, 27), "ok", Path(raw))

    def test_symlinked_descriptor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            outside = Path(raw) / "outside.md"
            _write(outside, _descriptor())
            descriptor = Path(raw) / "sources.slack-eng.md"
            descriptor.symlink_to(outside)

            with self.assertRaises(ValueError):
                ss.mark_checked(descriptor, date(2026, 8, 27), "ok", Path(raw))

            self.assertNotIn("2026-08-27", outside.read_text(encoding="utf-8"))

    def test_duplicate_watermark_field_is_rejected_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            original = _descriptor(last_checked="2026-08-02") + "- Last checked: 2026-08-02\n"
            _write(descriptor, original)

            with self.assertRaises(ValueError):
                ss.mark_checked(descriptor, date(2026, 8, 27), "ok", Path(raw))

            self.assertEqual(descriptor.read_text(encoding="utf-8"), original)

    def test_preexisting_temp_symlink_never_overwrites_target_or_replaces_descriptor(self) -> None:
        # Second-round review finding: a predictable ".tmp" sibling plus a plain
        # write_text() would follow a pre-planted symlink there, overwrite whatever it
        # points at, and then rename that symlink over the real descriptor.
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            _write(descriptor, _descriptor())
            outside = Path(raw).parent / "outside-target.md"
            _write(outside, "untouched\n")
            planted_tmp = descriptor.with_suffix(descriptor.suffix + ".tmp")
            planted_tmp.symlink_to(outside)

            ss.mark_checked(descriptor, date(2026, 8, 27), "ok", Path(raw))

            self.assertEqual(outside.read_text(encoding="utf-8"), "untouched\n")
            self.assertFalse(descriptor.is_symlink())
            self.assertIn("- Last checked: 2026-08-27", descriptor.read_text(encoding="utf-8"))

    def test_descriptor_swapped_to_symlink_after_the_earlier_check_is_rejected(self) -> None:
        # Third-round review finding: run_mark_checked()'s early is_symlink() check
        # and the later actual read were two separate operations; swapping the real
        # descriptor for a symlink in between made the read follow it and copy
        # external content into the (still-regular-file) descriptor. _read_no_follow()
        # closes the gap by making the read itself refuse to follow.
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            _write(descriptor, _descriptor())
            outside = Path(raw).parent / "outside-secret.md"
            _write(outside, "EXTERNAL-SECRET locator content\n")

            # Simulate the swap happening strictly after any earlier symlink check.
            descriptor.unlink()
            descriptor.symlink_to(outside)

            with self.assertRaises(ValueError):
                ss.mark_checked(descriptor, date(2026, 8, 27), "ok", Path(raw))

            self.assertEqual(outside.read_text(encoding="utf-8"), "EXTERNAL-SECRET locator content\n")

    def test_run_mark_checked_rejects_a_descriptor_swapped_between_its_own_precheck_and_the_write(self) -> None:
        # Fourth-round review finding: the test above only swaps the symlink BEFORE
        # mark_checked() is ever called, which is indistinguishable from
        # test_symlinked_descriptor_is_rejected -- it never exercises a genuine
        # mid-operation race. This test swaps the descriptor for a symlink strictly
        # BETWEEN run_mark_checked()'s own dry-run content pre-check and
        # mark_checked()'s later, independent read, proving the two reads don't trust
        # a shared snapshot.
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"
            outside = Path(raw).parent / "outside-secret.md"
            _write(outside, "EXTERNAL-SECRET locator content\n")

            real_read = ss._read_source_file_or_issue

            def swap_after_precheck(brain_root, path, label):
                result = real_read(brain_root, path, label)
                if path == descriptor:
                    descriptor.unlink()
                    descriptor.symlink_to(outside)
                return result

            with mock.patch.object(ss, "_read_source_file_or_issue", side_effect=swap_after_precheck):
                exit_code = ss.run_mark_checked(brain, date(2026, 8, 27), "slack-eng", "ok", apply=True)

            self.assertEqual(exit_code, 1)
            self.assertEqual(outside.read_text(encoding="utf-8"), "EXTERNAL-SECRET locator content\n")
            (SCRIPTS_DIR / "source_scheduler.log").unlink(missing_ok=True)

    def test_field_name_casing_accepted_by_decide_is_also_writable(self) -> None:
        # Third-round review finding: parse_fields()/decide_source() casefold field
        # names, so a descriptor with lowercase "- last checked:" was returned due,
        # but mark_checked()'s exact-case regex then rejected it as malformed --
        # scheduler and writer disagreed on the same file.
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            _write(
                descriptor,
                "# Source: slack-eng\n\n## Access\n- requires capability: chat.search\n"
                "- locator: x\n\n## Schedule\n- check cadence (days): 1\n"
                "- last checked: not checked\n- last status: not checked\n",
            )

            ss.mark_checked(descriptor, date(2026, 8, 27), "ok", Path(raw))
            updated = descriptor.read_text(encoding="utf-8")

        self.assertIn("2026-08-27", updated)
        self.assertIn("ok", updated)

    def test_field_name_casing_accepted_by_decide_survives_a_full_decide_then_write_round_trip(self) -> None:
        # Fourth-round review finding: the test above only exercises mark_checked()
        # directly with a hand-built descriptor -- it never calls decide_sources() at
        # all, so it can't actually prove the scheduler and the writer agree on the
        # same file. This builds a full registry + lowercase-cased descriptor, asks
        # decide_sources() whether it's due, and then writes through mark_checked()
        # using that same descriptor path, proving both ends of the contract hold on
        # one real file rather than two independently-asserted halves.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(_entry("slack-eng", "enabled", "messaging-tool")),
            )
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"
            _write(
                descriptor,
                "# Source: slack-eng\n\n## Access\n- requires capability: chat.search\n"
                "- locator: x\n\n## Schedule\n- check cadence (days): 1\n"
                "- last checked: not checked\n- last status: not checked\n",
            )
            _write_guide(brain)
            _write_profile(brain)

            decisions = ss.decide_sources(brain, date(2026, 8, 27))
            self.assertEqual(len(decisions), 1)
            self.assertTrue(decisions[0].due, decisions[0].reason)

            ss.mark_checked(descriptor, date(2026, 8, 27), "ok", brain)
            still_decisions = ss.decide_sources(brain, date(2026, 8, 27))

            self.assertIn("2026-08-27", descriptor.read_text(encoding="utf-8"))
            self.assertFalse(still_decisions[0].due)

    def test_apply_preserves_a_private_descriptor_mode(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            _write(descriptor, _descriptor())
            descriptor.chmod(0o600)

            ss.mark_checked(descriptor, date(2026, 8, 27), "ok", Path(raw))

            self.assertEqual(descriptor.stat().st_mode & 0o777, 0o600)

    def test_apply_leaves_no_temp_file_residue(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = Path(raw) / "sources.slack-eng.md"
            _write(descriptor, _descriptor())

            ss.mark_checked(descriptor, date(2026, 8, 27), "ok", Path(raw))

            leftovers = list(Path(raw).glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_write_refuses_a_symlinked_parent_directory_and_touches_nothing_external(self) -> None:
        # Fourth-round review finding: the write side of the same parent-directory-
        # swap gap as the registry read above. A pathname-based
        # `tempfile.mkstemp(dir=path.parent, ...)` re-resolves `path.parent` at call
        # time, so a symlinked parent would make BOTH the temp file's creation and
        # the final rename land inside the external directory the symlink points to,
        # not the brain. The dir-fd chain must refuse to open that parent at all.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "brain"
            (brain / "WIP").mkdir(parents=True)
            external = Path(raw) / "external-sources-dir"
            external.mkdir()
            _write(external / "sources.slack-eng.md", _descriptor())
            (brain / "WIP" / "SOURCES").symlink_to(external)
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"

            with self.assertRaises((OSError, ValueError)):
                ss.mark_checked(descriptor, date(2026, 8, 27), "ok", brain)

            self.assertEqual(sorted(p.name for p in external.iterdir()), ["sources.slack-eng.md"])
            self.assertNotIn("2026-08-27", (external / "sources.slack-eng.md").read_text(encoding="utf-8"))

    def test_extra_space_after_the_list_marker_is_writable_after_being_decided_due(self) -> None:
        # Fifth-round review finding: FIELD_RE (the parser) tolerates one-or-more
        # spaces after "-", but LAST_CHECKED_LINE_RE/LAST_STATUS_LINE_RE (the writer)
        # required exactly one literal space. A descriptor using two spaces (e.g.
        # "-  Last checked:") was returned due by decide_source() but rejected by
        # mark_checked() as missing the watermark lines -- a source accepted for
        # investigation could never be marked checked afterward.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(_entry("slack-eng", "enabled", "messaging-tool")),
            )
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"
            _write(
                descriptor,
                "# Source: slack-eng\n\n## Access\n\n-  Requires capability: chat.search\n"
                "-  Locator: x\n\n## Schedule\n\n-  Check cadence (days): 1\n"
                "-  Last checked: not checked\n-  Last status: not checked\n",
            )
            _write_guide(brain)
            _write_profile(brain)

            decisions = ss.decide_sources(brain, date(2026, 8, 27))
            self.assertEqual(len(decisions), 1)
            self.assertTrue(decisions[0].due, decisions[0].reason)

            ss.mark_checked(descriptor, date(2026, 8, 27), "ok", brain)

            self.assertIn("2026-08-27", descriptor.read_text(encoding="utf-8"))

    def test_write_rejects_a_descriptor_raced_to_a_symlink_instead_of_copying_its_target_mode(self) -> None:
        # Fifth-round review finding: `_atomic_write()`'s `os.stat(leaf, dir_fd=...)`
        # used the default follow_symlinks=True. If the leaf was swapped for a
        # symlink strictly after `mark_checked()`'s own safe read but before
        # `_atomic_write()` ran, the stat silently followed it and copied the
        # SYMLINK TARGET's mode onto the freshly written temp file -- e.g. turning a
        # private 0600 descriptor into 0644 (matching whatever the external target
        # happened to be) instead of rejecting the swap outright.
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"
            _write(descriptor, _descriptor())
            descriptor.chmod(0o600)
            outside = Path(raw).parent / "outside-target.md"
            _write(outside, "untouched\n")
            outside.chmod(0o644)

            real_atomic_write = ss._atomic_write

            def swap_then_write(path, content, brain_root):
                path.unlink()
                path.symlink_to(outside)
                real_atomic_write(path, content, brain_root)

            with mock.patch.object(ss, "_atomic_write", side_effect=swap_then_write):
                with self.assertRaises(OSError):
                    ss.mark_checked(descriptor, date(2026, 8, 27), "ok", brain)

            self.assertEqual(outside.read_text(encoding="utf-8"), "untouched\n")


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


class ListDueCliTests(unittest.TestCase):
    """Third-round review finding: main() called decide_sources() directly without
    ever checking registry_activated(), so the published CLI could dispatch a
    dormant brain's sources even though the tool doc claims it decides activation."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "source_scheduler.py"), *args],
            text=True, capture_output=True, check=False,
        )

    def test_list_due_reports_dormant_and_not_due_sources_when_not_activated(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)  # no WIP/WIP.md link written

            result = self._run("--brain-root", str(brain), "list-due")
            json_result = self._run("--brain-root", str(brain), "list-due", "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dormant", result.stdout)
        payload = json.loads(json_result.stdout)
        self.assertEqual(payload, {"activated": False, "decisions": []})

    def test_list_due_dispatches_once_activated(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            _write(brain / "WIP" / "WIP.md", "## Fuentes externas\n\n- [[sources.registry]]\n")

            result = self._run("--brain-root", str(brain), "list-due", "--json")

        payload = json.loads(result.stdout)
        self.assertTrue(payload["activated"])
        self.assertEqual(len(payload["decisions"]), 1)
        self.assertEqual(payload["decisions"][0]["slug"], "slack-eng")

    def test_invalid_date_argument_is_a_clean_failure_not_a_traceback(self) -> None:
        # Sixth-round review finding: --date was parsed with a bare
        # date.fromisoformat(args.date), so an invalid value raised an uncaught
        # ValueError and printed a Python traceback instead of a diagnostic and a
        # nonzero exit.
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)

            result = self._run("--brain-root", str(brain), "list-due", "--date", "not-a-date")

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("Invalid --date", result.stdout)


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
            self.assertIn("not safely readable", result.stdout)
            self.assertNotIn("2026", outside.read_text(encoding="utf-8"))
            (SCRIPTS_DIR / "source_scheduler.log").unlink(missing_ok=True)

    def test_dry_run_never_approves_a_mutation_apply_would_reject(self) -> None:
        # Second-round review finding: dry-run returned 0 on a descriptor missing
        # 'Last status:' and only apply discovered the problem, so a reviewed plan
        # could claim success for an update that was never actually going to happen.
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            descriptor = brain / "WIP" / "SOURCES" / "sources.slack-eng.md"
            text = descriptor.read_text(encoding="utf-8")
            descriptor.write_text(
                "\n".join(line for line in text.splitlines() if "Last status" not in line) + "\n",
                encoding="utf-8",
            )

            dry_run = self._run(
                "mark-checked", "--brain-root", str(brain),
                "--source", "slack-eng", "--status", "ok",
            )
            apply = self._run(
                "mark-checked", "--brain-root", str(brain),
                "--source", "slack-eng", "--status", "ok", "--apply",
            )

            self.assertEqual(dry_run.returncode, 1)
            self.assertEqual(apply.returncode, 1)
            (SCRIPTS_DIR / "source_scheduler.log").unlink(missing_ok=True)

    def test_apply_write_failure_is_reported_not_an_uncaught_exception(self) -> None:
        # Sixth-round review finding: run_mark_checked() only caught
        # (FileNotFoundError, ValueError) around mark_checked(), but an
        # environmental write failure (e.g. a non-writable SOURCES/ directory)
        # surfaces as a raw OSError from _atomic_write() -- it escaped as an
        # uncaught exception after the dry-run plan was already logged, instead of
        # the documented nonzero tool result.
        with tempfile.TemporaryDirectory() as raw:
            brain = _build_working_brain(raw)
            sources_dir = brain / "WIP" / "SOURCES"
            sources_dir.chmod(0o555)
            try:
                result = self._run(
                    "mark-checked", "--brain-root", str(brain),
                    "--source", "slack-eng", "--status", "ok", "--apply",
                )
            finally:
                sources_dir.chmod(0o755)
                (SCRIPTS_DIR / "source_scheduler.log").unlink(missing_ok=True)

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("mark-checked failed", result.stdout)


class ProfileSelectionConsistencyTests(unittest.TestCase):
    """Second-round review finding: the scheduler resolved a profile via
    `cwd=brain_root`, while live resolution (profile_context.py) uses the session's
    real cwd -- in a brain with per-project profiles, those two could select
    different profiles and disagree about which capabilities are routed."""

    def _brain_with_two_profiles(self, raw: str) -> Path:
        brain = Path(raw)
        _write(
            brain / "_AGENTS" / "SHARED" / "environment.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "default_profile": "default",
                    "project_rules": [{"path_prefix": str(brain / "project"), "profile": "project"}],
                }
            ),
        )
        _write(
            brain / "_AGENTS" / "SHARED" / "profiles" / "default.json",
            json.dumps(
                {
                    "schema_version": 1, "id": "default", "display_name": "Default",
                    "providers": {"m": {"kind": "manual", "service": "m", "required": False, "operations": {}}},
                    "capability_routes": {"chat.search": ["m"]},
                    "projects": [],
                }
            ),
        )
        _write(
            brain / "_AGENTS" / "SHARED" / "profiles" / "project.json",
            json.dumps(
                {
                    "schema_version": 1, "id": "project", "display_name": "Project",
                    "providers": {"m": {"kind": "manual", "service": "m", "required": False, "operations": {}}},
                    "capability_routes": {"issues.search": ["m"]},
                    "projects": [],
                }
            ),
        )
        return brain

    def test_scheduler_uses_the_profile_the_given_cwd_selects(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = self._brain_with_two_profiles(raw)
            (brain / "project").mkdir()

            default_routes, error = ss.capability_routes(brain, cwd=None)
            project_routes, _ = ss.capability_routes(brain, cwd=brain / "project")

        self.assertIsNone(error)
        self.assertEqual(default_routes, {"chat.search"})
        self.assertEqual(project_routes, {"issues.search"})

    def test_decide_sources_blocks_when_the_session_cwd_profile_lacks_the_capability(self) -> None:
        # The exact reproduction from the review: a source whose capability the
        # BRAIN-ROOT profile would route, but the session's real project profile
        # would not, must block using the profile the live subagent will actually use.
        with tempfile.TemporaryDirectory() as raw:
            brain = self._brain_with_two_profiles(raw)
            project_dir = brain / "project"
            project_dir.mkdir()
            _write(
                brain / "WIP" / "SOURCES" / "sources.registry.md",
                _registry(_entry("slack-eng", "enabled", "messaging-tool")),
            )
            _write(brain / "WIP" / "SOURCES" / "sources.slack-eng.md", _descriptor())
            _write_guide(brain)

            from_brain_root = ss.decide_sources(brain, date(2026, 8, 27), cwd=None)[0]
            from_project_cwd = ss.decide_sources(brain, date(2026, 8, 27), cwd=project_dir)[0]

        self.assertFalse(from_brain_root.blocked)
        self.assertTrue(from_project_cwd.blocked)
        self.assertIn("not routed", from_project_cwd.reason)


if __name__ == "__main__":
    unittest.main()

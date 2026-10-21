from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "brain" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from session_digest import (  # noqa: E402
    SessionDigestRequest,
    SessionDigestState,
    render_session_digest,
)
from session_open_context import collect_session_digest_state  # noqa: E402
from session_open_discovery import read_session_rollover_facts  # noqa: E402

SCAFFOLD = """---
tags: [session, wip]
---
# Session 2000-01-01 / topic / ses_fixture

## State
- Status: open

## Resume command
- `cd /fixture && opencode -s ses_fixture`

## Current objective
{objective}

## Immediate next step
{next_step}

## Consolidation checklist
- [ ] `WIP/WIP.md` updated if needed
"""


def note(objective: str = "- Work", next_step: str = "-") -> str:
    return SCAFFOLD.format(objective=objective, next_step=next_step)


class NextStepParserTests(unittest.TestCase):
    CASES = {
        "pending item": ("## Immediate next step\n- wait for CI\n", "present"),
        "pending prose": ("## Immediate next step\nReview the PR tomorrow.\n", "present"),
        "closure none": ("## Immediate next step\n- none\n", "none"),
        "closure sentence": ("## Immediate next step\nSession closed.\n", "none"),
        "none is not a prefix": ("## Immediate next step\n- none yet; wait for CI\n", "present"),
        "placeholder only": ("## Immediate next step\n-\n\n## Other\n- x\n", "missing"),
        "absent section": ("# S\n\n## State\n- Status: open\n", "missing"),
        "comment only": ("## Immediate next step\n<!-- todo -->\n", "missing"),
        "multiline comment": ("## Immediate next step\n<!--\n- hidden\n-->\n", "missing"),
        "fenced example": ("## Immediate next step\n```\n- example\n```\n", "missing"),
        "nested heading keeps section": (
            "## Immediate next step\n### Detail\n- do the thing\n",
            "present",
        ),
        "section ends at next level-2 heading": (
            "## Immediate next step\n- none\n\n## Other\n- pending elsewhere\n",
            "none",
        ),
        "conflicting closure and pending": ("## Immediate next step\n- none\n- review PR\n", "unknown"),
        "duplicate section": (
            "## Immediate next step\n- a\n\n## Immediate next step\n- b\n",
            "unknown",
        ),
        "unclosed comment": ("## Immediate next step\n<!-- oops\n- a\n", "unknown"),
        "unclosed fence": ("## Immediate next step\n```\n- a\n", "unknown"),
        "tilde fenced example": ("## Immediate next step\n~~~md\n- sample pending task\n~~~\n", "missing"),
        "longer fence containing a shorter one": (
            "## Immediate next step\n````\n```\n- sample\n```\n````\n",
            "missing",
        ),
        "mismatched fence delimiters": ("## Immediate next step\n~~~\n- a\n```\n", "unknown"),
        "closure with an inline comment": ("## Immediate next step\n- none <!-- all finished -->\n", "none"),
        "pending after an inline comment": ("## Immediate next step\n<!-- x --> - wait for CI\n", "present"),
        "pending after a fenced example": ("## Immediate next step\n```\nx\n```\n- wait for CI\n", "present"),
        "unbalanced comment inside a fence": (
            "## Immediate next step\n```html\n<!--\n```\n- wait for CI\n",
            "present",
        ),
        "fence marker inside a comment": ("## Immediate next step\n<!--\n```\n-->\n- wait\n", "present"),
        "fence before the section": ("```\n## Immediate next step\n```\n## Immediate next step\n- go\n", "present"),
    }

    def classify(self, content: str | bytes) -> str:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "2000-01-01-session-ses_a-t.md"
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
            return read_session_rollover_facts(path).next_step

    def test_classification_table(self) -> None:
        for name, (content, expected) in self.CASES.items():
            with self.subTest(name):
                self.assertEqual(self.classify(content), expected)

    def test_invalid_utf8_is_unknown(self) -> None:
        self.assertEqual(self.classify(b"## Immediate next step\n- \xff\xfe\n"), "unknown")

    def test_missing_file_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            self.assertEqual(read_session_rollover_facts(Path(raw) / "gone.md").next_step, "unknown")


class CollectionTests(unittest.TestCase):
    TODAY = "2000-01-02"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.brain = Path(self._tmp.name)
        (self.brain / "WIP" / "SESSIONS").mkdir(parents=True)
        (self.brain / "JOURNAL").mkdir()
        (self.brain / "JOURNAL" / f"{self.TODAY}.md").write_text("# Sessions\n", encoding="utf-8")

    def write(self, name: str, content: str | bytes) -> str:
        path = self.brain / "WIP" / "SESSIONS" / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return f"WIP/SESSIONS/{name}"

    def collect(self) -> SessionDigestState:
        return collect_session_digest_state(
            SessionDigestRequest(
                brain_root=str(self.brain),
                session_id="ses_current",
                runtime="codex",
                session_label="topic",
                cwd="/fixture",
                prepare_daily=False,
                apply=False,
                today=self.TODAY,
            )
        )

    def test_peers_get_next_step_facts_and_empty_notes_keep_their_flag(self) -> None:
        pending = self.write("2000-01-01-session-ses_a-t.md", note(next_step="- wait for CI"))
        closed = self.write("2000-01-01-session-ses_b-t.md", note(next_step="- none"))
        missing = self.write("2000-01-01-session-ses_c-t.md", note())
        empty = self.write("2000-01-01-session-ses_d-t.md", note(objective="-"))
        self.write("2000-01-01-session-ses_e-t.md", note().replace("Status: open", "Status: consolidated"))

        state = self.collect()

        self.assertEqual(
            dict(state.open_session_next_steps),
            {pending: "present", closed: "none", missing: "missing"},
        )
        self.assertEqual(state.empty_open_sessions, (empty,))
        rendered = render_session_digest(state)
        self.assertIn(f"- {pending}  next_step=present\n", rendered)
        self.assertIn(f"- {empty}  ⚠ empty note", rendered)
        self.assertNotIn(f"{empty}  next_step", rendered)

    def test_current_note_is_excluded(self) -> None:
        self.write(f"{self.TODAY}-session-ses_current-topic.md", note(next_step="- continue"))
        peer = self.write("2000-01-01-session-ses_a-t.md", note(next_step="- wait"))

        state = self.collect()

        self.assertEqual(dict(state.open_session_next_steps), {peer: "present"})

    def test_reused_prior_day_note_is_excluded(self) -> None:
        self.write("1999-12-30-session-ses_current-old.md", note(next_step="- continue"))
        peer = self.write("2000-01-01-session-ses_a-t.md", note(next_step="- wait"))

        state = self.collect()

        self.assertEqual(dict(state.open_session_next_steps), {peer: "present"})

    def test_undecodable_peer_degrades_without_aborting_or_flagging_empty(self) -> None:
        bad = self.write(
            "2000-01-01-session-ses_a-t.md",
            note(objective="-", next_step="-").encode("utf-8") + b"\n\xff\xfe\n",
        )

        state = self.collect()

        self.assertIn(bad, state.open_sessions)
        self.assertEqual(dict(state.open_session_next_steps), {bad: "unknown"})
        self.assertNotIn(bad, state.empty_open_sessions)

    def test_peer_disappearing_after_status_detection_degrades_conservatively(self) -> None:
        import session_open_context as context

        path = self.brain / "WIP" / "SESSIONS" / "2000-01-01-session-ses_a-t.md"
        path.write_text(note(objective="-"), encoding="utf-8")
        real = context.is_session_open

        def open_then_vanish(candidate: Path) -> bool:
            result = real(candidate)
            candidate.unlink(missing_ok=True)
            return result

        from unittest.mock import patch

        with patch.object(context, "is_session_open", open_then_vanish):
            state = self.collect()

        rel = "WIP/SESSIONS/2000-01-01-session-ses_a-t.md"
        self.assertIn(rel, state.open_sessions)
        self.assertNotIn(rel, state.empty_open_sessions)
        self.assertEqual(dict(state.open_session_next_steps), {rel: "unknown"})

    def test_unreadable_peer_never_gets_the_empty_flag(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("permission bits do not restrict root")
        path = self.brain / "WIP" / "SESSIONS" / "2000-01-01-session-ses_a-t.md"
        path.write_text(note(objective="-"), encoding="utf-8")
        path.chmod(0o000)
        self.addCleanup(path.chmod, 0o644)

        state = self.collect()

        self.assertEqual(state.empty_open_sessions, ())
        self.assertEqual(state.open_session_next_steps, ())


class FixtureAndRuleContractTests(unittest.TestCase):
    def test_a_fixture_with_next_steps_collects_and_renders_without_touching_the_host(self) -> None:
        from dataclasses import replace

        from session_digest import fixed_session_digest_fixture_data, fixed_session_digest_request

        path = "WIP/SESSIONS/1999-12-31-session-previous.md"
        fixture = replace(
            fixed_session_digest_fixture_data(),
            open_session_next_steps=((path, "present"),),
        )
        request = replace(fixed_session_digest_request(), fixture_data=fixture)

        state = collect_session_digest_state(request)

        self.assertEqual(state.open_session_next_steps, ((path, "present"),))
        self.assertIn(f"- {path}  next_step=present\n", render_session_digest(state))

    def test_the_rule_skips_only_present_and_keeps_empty_peers_in_the_pass(self) -> None:
        rule = (Path(__file__).resolve().parents[1] / "model" / "RULES-SESSION-LIFECYCLE.common.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Only `present` skips the pass", rule)
        self.assertIn("including peers that carry the empty-note flag", rule)
        self.assertIn("explicit session review and the recurring stale-session inspection", rule)


class DigestScaleTests(unittest.TestCase):
    def render(self, peers: int) -> str:
        paths = tuple(f"WIP/SESSIONS/2000-01-01-session-ses_{n:03d}-t.md" for n in range(peers))
        state = SessionDigestState(
            mode="dry-run",
            brain_root="/fixture/brain",
            today="2000-01-02",
            today_daily_exists=True,
            latest_daily="2000-01-02.md",
            day_rollover_detected=False,
            session_id="fixture-session",
            runtime="codex",
            cwd="/fixture/project",
            topic="fixture-session",
            session_note="WIP/SESSIONS/x.md",
            note_action="creating",
            daily_update="JOURNAL/2000-01-02.md",
            daily_action="upserting",
            open_sessions=paths,
            operational_files=(),
            wip_context=(),
            task_types=(),
            maintenance_jobs=(),
            sources_due=(),
            injected_project_agents=False,
            open_session_next_steps=tuple((path, "present") for path in paths),
        )
        return render_session_digest(state)

    def test_growth_is_linear_and_adds_one_short_suffix_per_peer(self) -> None:
        small, large = self.render(17), self.render(100)
        suffix = "  next_step=present"
        self.assertEqual(large.count(suffix), 100)
        base_small = small.replace(suffix, "")
        base_large = large.replace(suffix, "")
        self.assertEqual(len(small) - len(base_small), 17 * len(suffix.encode("utf-8")))
        self.assertEqual(len(large) - len(base_large), 100 * len(suffix.encode("utf-8")))
        for line in large.splitlines():
            if "next_step=" in line:
                self.assertTrue(line.endswith(suffix))
                self.assertNotIn("wait", line)

    def test_peers_without_facts_render_plain_lines(self) -> None:
        rendered = self.render(2).replace("  next_step=present", "")
        self.assertIn("- WIP/SESSIONS/2000-01-01-session-ses_000-t.md\n", rendered)


if __name__ == "__main__":
    unittest.main()

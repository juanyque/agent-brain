from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "brain" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from session_digest import SessionDigestState, render_session_digest  # noqa: E402
from session_open_discovery import (  # noqa: E402
    empty_open_session_paths,
    is_session_note_empty,
    session_note_date,
)

SCAFFOLD = """---
tags: [session, wip]
---
<!-- content-boundary: {"kind":"template"} -->
# Session 2000-01-01 / topic / ses_fixture

## State
- Status: open
- Allowed values: open, handoff-only, consolidated, stale-follow-up

## Resume command
- `cd /fixture && opencode -s ses_fixture`
- Working directory: `/fixture`

## Current objective
-

## Decisions taken
-

## Working assumptions
-

## Open questions
-

## Immediate next step
-

## Consolidation checklist
- [ ] `WIP/WIP.md` updated if needed
- [ ] `JOURNAL/` updated if needed
"""


class SessionNoteDateTests(unittest.TestCase):
    def test_extracts_leading_date(self) -> None:
        self.assertEqual(
            session_note_date(Path("2000-01-01-session-ses_x-topic.md")), "2000-01-01"
        )

    def test_returns_none_without_date_prefix(self) -> None:
        self.assertIsNone(session_note_date(Path("notes-ses_x-topic.md")))


class SessionNoteEmptyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, content: str, name: str = "2000-01-01-session-ses_a-t.md") -> Path:
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_pure_scaffold_is_empty(self) -> None:
        self.assertTrue(is_session_note_empty(self.write(SCAFFOLD)))

    def test_objective_line_marks_worked(self) -> None:
        content = SCAFFOLD.replace(
            "## Current objective\n-", "## Current objective\n- Real work"
        )
        self.assertFalse(is_session_note_empty(self.write(content)))

    def test_checked_box_marks_worked(self) -> None:
        content = SCAFFOLD.replace("- [ ] `WIP/WIP.md`", "- [x] `WIP/WIP.md`")
        self.assertFalse(is_session_note_empty(self.write(content)))

    def test_unchecked_box_outside_checklist_marks_worked(self) -> None:
        content = SCAFFOLD.replace(
            "## Immediate next step\n-",
            "## Immediate next step\n- [ ] Investigate production failure",
        )
        self.assertFalse(is_session_note_empty(self.write(content)))

    def test_content_in_shell_sections_stays_empty(self) -> None:
        content = SCAFFOLD.replace(
            "## Resume command\n- `cd /fixture",
            "## Resume command\n- heavy prose about resuming\n- `cd /fixture",
        )
        self.assertTrue(is_session_note_empty(self.write(content)))

    def test_unclosed_frontmatter_is_worked(self) -> None:
        self.assertFalse(is_session_note_empty(self.write("---\ntags: [session]\n")))

    def test_multiline_comment_is_ignored(self) -> None:
        content = SCAFFOLD.replace(
            "<!-- content-boundary: {\"kind\":\"template\"} -->",
            "<!-- first line\nsecond line\nthird -->",
        )
        self.assertTrue(is_session_note_empty(self.write(content)))

    def test_unclosed_comment_is_worked(self) -> None:
        content = SCAFFOLD.replace(
            "<!-- content-boundary: {\"kind\":\"template\"} -->",
            "<!-- never closed",
        )
        self.assertFalse(is_session_note_empty(self.write(content)))

    def test_content_after_comment_close_marks_worked(self) -> None:
        content = SCAFFOLD.replace(
            "<!-- content-boundary: {\"kind\":\"template\"} -->",
            "<!-- c --> - real recorded work",
        )
        self.assertFalse(is_session_note_empty(self.write(content)))

    def test_no_frontmatter_scaffold_is_empty(self) -> None:
        content = SCAFFOLD.split("-->\n", 1)[1]
        self.assertTrue(is_session_note_empty(self.write(content)))

    def test_mid_document_horizontal_rule_marks_worked(self) -> None:
        content = SCAFFOLD.split("-->\n", 1)[1].replace(
            "## Current objective\n-",
            "## Current objective\n---\n- Real recorded work\n---",
        )
        self.assertFalse(is_session_note_empty(self.write(content)))

    def test_heading_with_trailing_spaces_sets_section(self) -> None:
        content = SCAFFOLD.replace(
            "## Consolidation checklist",
            "## Consolidation checklist  ",
        )
        self.assertTrue(is_session_note_empty(self.write(content)))


class EmptyOpenSessionPathsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.sessions = self.root / "WIP" / "SESSIONS"
        self.sessions.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_session(self, name: str, content: str) -> str:
        (self.sessions / name).write_text(content, encoding="utf-8")
        return f"WIP/SESSIONS/{name}"

    def test_flags_yesterday_scaffold_only(self) -> None:
        empty = self.write_session("2000-01-01-session-ses_a-t.md", SCAFFOLD)
        worked = self.write_session(
            "2000-01-01-session-ses_b-t.md",
            SCAFFOLD.replace("## Current objective\n-", "## Current objective\n- Work"),
        )
        today = self.write_session("2000-01-02-session-ses_c-t.md", SCAFFOLD)
        undated = self.write_session("session-ses_d-t.md", SCAFFOLD)
        result = empty_open_session_paths(
            self.root, (empty, worked, today, undated), "2000-01-02"
        )
        self.assertEqual(result, (empty,))

    def test_no_flag_when_all_sessions_are_from_today(self) -> None:
        today = self.write_session("2000-01-02-session-ses_c-t.md", SCAFFOLD)
        result = empty_open_session_paths(self.root, (today,), "2000-01-02")
        self.assertEqual(result, ())

    def test_excluded_current_session_is_not_flagged(self) -> None:
        resumed = self.write_session("2000-01-01-session-ses_a-t.md", SCAFFOLD)
        orphan = self.write_session("2000-01-01-session-ses_b-t.md", SCAFFOLD)
        result = empty_open_session_paths(
            self.root,
            (resumed, orphan),
            "2000-01-02",
            exclude=frozenset({resumed}),
        )
        self.assertEqual(result, (orphan,))


class DigestEmptyFlagTests(unittest.TestCase):
    FLAGGED = "WIP/SESSIONS/2000-01-01-session-ses_a-t.md"
    PLAIN = "WIP/SESSIONS/2000-01-02-session-ses_b-t.md"

    def _render(self, empty: tuple[str, ...]) -> str:
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
            open_sessions=(self.FLAGGED, self.PLAIN),
            operational_files=(),
            wip_context=(),
            task_types=(),
            maintenance_jobs=(),
            sources_due=(),
            injected_project_agents=False,
            empty_open_sessions=empty,
        )
        return render_session_digest(state)

    def test_flag_attaches_to_the_right_session_line(self) -> None:
        rendered = self._render((self.FLAGGED,))
        self.assertIn(
            f"- {self.FLAGGED}  ⚠ empty (never worked) — close it or resume it\n",
            rendered,
        )
        self.assertIn(f"- {self.PLAIN}\n", rendered)

    def test_no_flag_renders_plain_lines(self) -> None:
        rendered = self._render(())
        self.assertNotIn("⚠", rendered)
        self.assertIn(f"- {self.FLAGGED}\n", rendered)
        self.assertIn(f"- {self.PLAIN}\n", rendered)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "skills" / "brain" / "scripts"))

import cleanup_empty_action_categories as cleanup  # noqa: E402
import daily_report_write as writer  # noqa: E402

TEMPLATE = REPO_ROOT / "model" / "TEMPLATES" / "TEMPLATE.daily-note.common.md"
TODAY = "2026-03-11"
REPORT = "## Sprint\n**PROJ-1 / SLUG:** the goal of this task is X.\n- detail\n\n## Blockers\nNone."


def template_daily() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    text = re.sub(r"<% tp\.date\.yesterday\(\) %>", "2026-03-10", text)
    text = re.sub(r"<% tp\.date\.tomorrow\(\) %>", "2026-03-12", text)
    return text.replace("<% tp.file.cursor() %>", "")


class TemplateShapeTests(unittest.TestCase):
    def test_template_places_daily_report_between_sessions_and_actions(self) -> None:
        headings = [line for line in template_daily().splitlines() if line.startswith("# ")]
        self.assertEqual(headings[:3], ["# Sessions", "# Daily report", "# Actions"])


class RenderTests(unittest.TestCase):
    def test_fills_the_empty_template_section(self) -> None:
        text = template_daily()
        new, action = writer.render(text, REPORT, "2026-03-09..2026-03-11")
        self.assertEqual(action, "fill-empty-section")
        self.assertIn("# Daily report\n\n<!-- daily-report range=2026-03-09..2026-03-11 -->\n## Sprint", new)
        self.assertIn("None.\n<!-- /daily-report -->\n\n# Actions", new)
        self.assertEqual(new.replace(new[new.index("# Daily report"): new.index("# Actions")], ""), text.replace(text[text.index("# Daily report"): text.index("# Actions")], ""))

    def test_inserts_the_section_before_actions_when_the_note_lacks_it(self) -> None:
        legacy = template_daily().replace("# Daily report\n\n", "")
        new, action = writer.render(legacy, REPORT, "2026-03-09..2026-03-11")
        self.assertEqual(action, "insert-section")
        headings = [line for line in new.splitlines() if line.startswith("# ")]
        self.assertEqual(headings[:3], ["# Sessions", "# Daily report", "# Actions"])

    def test_appends_the_section_when_there_is_no_actions_block(self) -> None:
        new, action = writer.render("---\ntags: [daily]\n---\n# Sessions\n- one\n", REPORT, "2026-03-09..2026-03-11")
        self.assertEqual(action, "insert-section")
        self.assertTrue(new.endswith("<!-- /daily-report -->\n"))
        self.assertIn("- one\n\n# Daily report", new)

    def test_rerun_with_another_range_replaces_the_report_and_keeps_the_rest(self) -> None:
        first, _ = writer.render(template_daily(), REPORT, "2026-03-11..2026-03-11")
        second, action = writer.render(first, "## Sprint\nnew text", "2026-03-06..2026-03-11")
        self.assertEqual(action, "replace-report")
        self.assertEqual(second.count("<!-- daily-report range="), 1)
        self.assertIn("range=2026-03-06..2026-03-11", second)
        self.assertNotIn("the goal of this task is X", second)
        self.assertEqual(second.split("<!-- daily-report")[0], first.split("<!-- daily-report")[0])
        self.assertEqual(second.split("<!-- /daily-report -->")[1], first.split("<!-- /daily-report -->")[1])

    def test_same_input_is_idempotent(self) -> None:
        once, _ = writer.render(template_daily(), REPORT, "2026-03-09..2026-03-11")
        twice, _ = writer.render(once, REPORT, "2026-03-09..2026-03-11")
        self.assertEqual(once, twice)

    def test_refuses_to_overwrite_unmanaged_content(self) -> None:
        text = template_daily().replace("# Daily report\n", "# Daily report\nmy own notes\n")
        with self.assertRaisesRegex(ValueError, "not a managed report"):
            writer.render(text, REPORT, "2026-03-09..2026-03-11")

    def test_refuses_malformed_markers(self) -> None:
        good, _ = writer.render(template_daily(), REPORT, "2026-03-09..2026-03-11")
        with self.assertRaisesRegex(ValueError, "malformed"):
            writer.render(good.replace("<!-- /daily-report -->", ""), REPORT, "2026-03-09..2026-03-11")
        swapped = good.replace("<!-- /daily-report -->", "<!-- daily-report range=2026-03-01..2026-03-02 -->")
        with self.assertRaisesRegex(ValueError, "malformed"):
            writer.render(swapped, REPORT, "2026-03-09..2026-03-11")

    def test_refuses_reports_that_would_break_the_section_structure(self) -> None:
        text = template_daily()
        for bad, message in (
            ("", "empty"),
            ("   \n\n", "empty"),
            ("# Top level\nbody", "top-level"),
            ("## ok\n<!-- /daily-report -->", "markers"),
            ("<!-- daily-report range=x -->", "markers"),
        ):
            with self.subTest(report=bad):
                with self.assertRaisesRegex(ValueError, message):
                    writer.render(text, bad, "2026-03-09..2026-03-11")

    def test_validates_the_range(self) -> None:
        for bad in ("2026-03-09", "2026-03-11..2026-03-09", "2026/03/09..2026/03/11"):
            with self.subTest(range=bad):
                with self.assertRaises(ValueError):
                    writer.validate_range(bad)


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.brain = Path(self._tmp.name) / "brain"
        (self.brain / "JOURNAL").mkdir(parents=True)
        self.note = self.brain / "JOURNAL" / f"{TODAY}.md"
        self.note.write_text(template_daily(), encoding="utf-8")
        self.report = Path(self._tmp.name) / "report.md"
        self.report.write_text(REPORT, encoding="utf-8")
        self.log = Path(self._tmp.name) / "run.log"

    def run_cli(self, *extra: str, date_args: tuple[str, ...] = ()) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        argv = [
            "--brain-root", str(self.brain), "--report-file", str(self.report),
            "--range", "2026-03-09..2026-03-11", "--today", TODAY, "--log-path", str(self.log),
            *date_args, *extra,
        ]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = writer.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_is_the_default_and_writes_nothing(self) -> None:
        before = self.note.read_text(encoding="utf-8")
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("mode: dry-run", out)
        self.assertIn("action: fill-empty-section", out)
        self.assertEqual(self.note.read_text(encoding="utf-8"), before)
        self.assertFalse(self.log.exists())

    def test_apply_writes_verifies_and_logs_then_rerun_is_stable(self) -> None:
        code, out, _ = self.run_cli("--apply")
        self.assertEqual(code, 0)
        self.assertIn("written and verified", out)
        written = self.note.read_text(encoding="utf-8")
        self.assertIn("<!-- daily-report range=2026-03-09..2026-03-11 -->", written)
        self.assertTrue(self.log.exists())
        code, out, _ = self.run_cli("--apply")
        self.assertEqual(code, 0)
        self.assertIn("action: replace-report", out)
        self.assertEqual(self.note.read_text(encoding="utf-8"), written)

    def test_refuses_any_day_other_than_today(self) -> None:
        past = self.brain / "JOURNAL" / "2026-03-10.md"
        past.write_text(template_daily(), encoding="utf-8")
        code, _, err = self.run_cli("--apply", date_args=("--date", "2026-03-10"))
        self.assertEqual(code, 2)
        self.assertIn("only today's note", err)
        self.assertNotIn("daily-report", past.read_text(encoding="utf-8"))

    def test_never_creates_a_missing_daily(self) -> None:
        self.note.unlink()
        code, _, err = self.run_cli("--apply")
        self.assertEqual(code, 2)
        self.assertIn("no daily note", err)
        self.assertFalse(self.note.exists())

    def test_refuses_a_symlinked_daily(self) -> None:
        target = Path(self._tmp.name) / "elsewhere.md"
        target.write_text(template_daily(), encoding="utf-8")
        self.note.unlink()
        self.note.symlink_to(target)
        code, _, err = self.run_cli("--apply")
        self.assertEqual(code, 2)
        self.assertNotIn("daily-report", target.read_text(encoding="utf-8"))
        self.assertTrue(err.startswith("ERROR:"))

    def test_invalid_report_exits_2_without_writing(self) -> None:
        self.report.write_text("# Top level", encoding="utf-8")
        before = self.note.read_text(encoding="utf-8")
        code, _, err = self.run_cli("--apply")
        self.assertEqual(code, 2)
        self.assertIn("top-level", err)
        self.assertEqual(self.note.read_text(encoding="utf-8"), before)


class CleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.note = Path(self._tmp.name) / "2026-03-10.md"

    def clean(self, text: str, apply: bool = True) -> tuple[bool, list[tuple[str, str]], str]:
        self.note.write_text(text, encoding="utf-8")
        changed, removed = cleanup.process_file(self.note, apply=apply)
        return changed, removed, self.note.read_text(encoding="utf-8")

    def test_an_empty_report_section_is_removed_with_the_rest_untouched(self) -> None:
        template = template_daily()
        changed, removed, text = self.clean(template)
        self.assertTrue(changed)
        self.assertIn(("Daily report", "empty section"), removed)
        self.assertNotIn("# Daily report", text)
        self.assertIn("# Sessions\n\n# Actions", text)

    def test_a_filled_report_section_survives_the_cleanup(self) -> None:
        filled, _ = writer.render(template_daily(), REPORT, "2026-03-09..2026-03-11")
        changed, removed, text = self.clean(filled)
        self.assertNotIn("Daily report", [name for name, _ in removed])
        self.assertIn("<!-- daily-report range=2026-03-09..2026-03-11 -->", text)
        self.assertIn("## Blockers\nNone.", text)
        self.assertTrue(changed)  # the empty action placeholders are still removed

    def test_dry_run_does_not_touch_the_note(self) -> None:
        template = template_daily()
        changed, removed, text = self.clean(template, apply=False)
        self.assertTrue(changed)
        self.assertEqual(text, template)

    def test_a_report_section_in_the_last_position_is_handled(self) -> None:
        text = "---\ntags: [daily]\n---\n# Sessions\n\n# Actions\n* [[LEARN]]:\n\n# Daily report\n\n"
        changed, removed, out = self.clean(text)
        self.assertIn(("Daily report", "empty section"), removed)
        self.assertNotIn("# Daily report", out)
        self.assertIn("# Actions", out)


if __name__ == "__main__":
    unittest.main()

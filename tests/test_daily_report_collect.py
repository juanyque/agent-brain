from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "brain" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import daily_report_collect as collector  # noqa: E402

TODAY = date(2026, 3, 11)


def _write(path: Path, text: str, day: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if day:
        stamp = datetime.fromisoformat(f"{day}T12:00:00").timestamp()
        os.utime(path, (stamp, stamp))
    return path


def _daily(sessions: list[str], work: list[str]) -> str:
    return (
        "---\ntags: [daily]\n---\n# Sessions\n"
        + "".join(f"{line}\n" for line in sessions)
        + "\n# Actions\n* [[LEARN]]:\n* [[WORK]]:\n"
        + "".join(f"{line}\n" for line in work)
        + "* [[TODO]]:\n"
    )


def _session(status: str, objective: str, next_step: str) -> str:
    return (
        "---\ntags: [session]\n---\n# Session\n\n## State\n"
        f"- Status: {status}\n\n## Current objective\n- {objective}\n\n"
        f"## Open questions\n-\n\n## Immediate next step\n- {next_step}\n"
    )


ISSUE = """---
tags: [issue, wip]
issue_id: PROJ-1
status: in-progress
work_type: sprint
url: https://tracker.example/PROJ-1
---
# PROJ-1: Example

> Example summary line

## Status

### 2026-03-06: older entry
- Old work.

### 2026-03-09: in range
- New work.

## References
"""


class DailyReportCollectTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.brain = Path(self._tmp.name)
        sid_a, sid_b, sid_c = "aaaa1111", "bbbb2222", "cccc3333"
        self.note_a = f"2026-03-06-session-{sid_a}-first"
        self.note_b = f"2026-03-09-session-{sid_b}-second"
        _write(
            self.brain / "JOURNAL" / "2026-03-05.md",
            _daily([], ["  * [[proj]] — before the range"]),
            "2026-03-05",
        )
        _write(
            self.brain / "JOURNAL" / "2026-03-06.md",
            _daily(
                [f"- `cd /w && claude --resume {sid_a}` — first. Session note: [[{self.note_a}]]."],
                ["  * [[proj]]", "    * did the first thing"],
            ),
            "2026-03-06",
        )
        _write(
            self.brain / "JOURNAL" / "2026-03-09.md",
            _daily(
                [f"- `cd /w && codex resume {sid_b}` — second. Session note: [[{self.note_b}]]."],
                ["  * [[proj]]", "    * did the second thing"],
            ),
            "2026-03-09",
        )
        sessions = self.brain / "WIP" / "SESSIONS"
        _write(sessions / f"{self.note_a}.md", _session("consolidated", "first goal", "none"), "2026-03-06")
        _write(sessions / f"{self.note_b}.md", _session("open", "second goal", "keep going"), "2026-03-09")
        _write(
            sessions / f"2026-02-01-session-{sid_c}-unregistered.md",
            _session("open", "unregistered goal", "wait"),
            "2026-03-10",
        )
        _write(
            sessions / "2026-02-02-session-dddd4444-untouched.md",
            _session("open", "old goal", "wait"),
            "2026-02-02",
        )
        issue_dir = self.brain / "WIP" / "area" / "repo" / "PROJ-1 - Example"
        _write(issue_dir / "PROJ-1 - Example.md", ISSUE, "2026-03-10")
        _write(
            issue_dir / "proj-1.analysis.md",
            "---\ntags: [issue]\nissue_id: PROJ-1\n---\n# Analysis\n",
            "2026-03-10",
        )
        _write(
            self.brain / "WIP" / "area" / "repo" / "PROJ-2 - Stale" / "PROJ-2 - Stale.md",
            ISSUE.replace("PROJ-1", "PROJ-2").replace("2026-03-09", "2026-01-09"),
            "2026-02-15",
        )
        _write(self.brain / "OUTBOX" / "proj-1-run" / "result.log", "ok\n", "2026-03-09")
        _write(self.brain / "OUTBOX" / "orphan" / "stray.txt", "x\n", "2026-03-09")
        _write(self.brain / "OUTBOX" / "old" / "gone.txt", "x\n", "2026-01-01")

    def run_collect(self, start: date | None = None, end: date = TODAY) -> dict[str, object]:
        return collector.collect(self.brain, start, end, TODAY)

    def test_default_start_is_latest_daily_before_today(self) -> None:
        result = self.run_collect()
        self.assertEqual(result["range"], {"from": "2026-03-09", "to": "2026-03-11", "today": "2026-03-11"})
        self.assertEqual([d["date"] for d in result["days"]], ["2026-03-09"])

    def test_explicit_start_includes_every_daily_in_range_and_excludes_earlier(self) -> None:
        result = self.run_collect(date(2026, 3, 6))
        self.assertEqual([d["date"] for d in result["days"]], ["2026-03-06", "2026-03-09"])
        self.assertEqual(result["missing_dailies"], [])
        work = [line for d in result["days"] for line in d["work"]]
        self.assertIn("    * did the second thing", work)
        self.assertNotIn("  * [[proj]] — before the range", work)

    def test_missing_start_daily_is_reported(self) -> None:
        result = self.run_collect(date(2026, 3, 7))
        self.assertEqual(result["missing_dailies"], ["2026-03-07"])

    def test_sessions_registered_unregistered_and_untouched(self) -> None:
        result = self.run_collect(date(2026, 3, 6))
        by_id = {s["session_id"]: s for s in result["sessions"] if s["session_id"]}
        self.assertEqual(set(by_id), {"aaaa1111", "bbbb2222"})
        self.assertEqual(by_id["aaaa1111"]["status"], "consolidated")
        self.assertEqual(by_id["bbbb2222"]["objective"], ["- second goal"])
        self.assertEqual(by_id["bbbb2222"]["next_step"], ["- keep going"])
        self.assertEqual(by_id["bbbb2222"]["registered_in"], ["2026-03-09"])
        extra = [s for s in result["sessions"] if not s["session_id"]]
        self.assertEqual([s["reason"] for s in extra], ["modified-in-range"])
        self.assertIn("unregistered", extra[0]["path"])
        self.assertFalse(any("untouched" in s["path"] for s in result["sessions"]))

    def test_registered_session_without_note_is_a_warning_not_a_crash(self) -> None:
        _write(
            self.brain / "JOURNAL" / "2026-03-10.md",
            _daily(["- `cd /w && claude --resume ffff6666` — gone. Session note: [[2026-03-10-session-ffff6666-gone]]."], []),
            "2026-03-10",
        )
        result = self.run_collect(date(2026, 3, 10))
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("ffff6666", result["warnings"][0])

    def test_issue_dated_entries_are_filtered_and_facets_attached(self) -> None:
        result = self.run_collect(date(2026, 3, 9))
        issues = {i["issue_id"]: i for i in result["issues"]}
        self.assertEqual(set(issues), {"PROJ-1"})
        issue = issues["PROJ-1"]
        self.assertEqual(issue["work_type"], "sprint")
        self.assertEqual(issue["summary"], "Example summary line")
        self.assertEqual([e["date"] for e in issue["dated_entries"]], ["2026-03-09"])
        self.assertEqual(issue["dated_entries"][0]["lines"], ["- New work."])
        self.assertEqual(len(issue["facets"]), 1)
        self.assertTrue(issue["facets"][0].endswith("proj-1.analysis.md"))

    def test_issue_without_work_type_is_reported_empty(self) -> None:
        note = self.brain / "WIP" / "area" / "repo" / "PROJ-1 - Example" / "PROJ-1 - Example.md"
        _write(note, ISSUE.replace("work_type: sprint\n", "work_type:  # sprint | unplanned\n"), "2026-03-10")
        result = self.run_collect(date(2026, 3, 9))
        self.assertEqual(result["issues"][0]["work_type"], "")

    def test_generated_files_are_filtered_by_range_and_attributed(self) -> None:
        result = self.run_collect(date(2026, 3, 9))
        files = {f["path"]: f for f in result["generated_files"]}
        self.assertEqual(set(files), {"OUTBOX/proj-1-run/result.log", "OUTBOX/orphan/stray.txt"})
        self.assertEqual(files["OUTBOX/proj-1-run/result.log"]["referenced_by"], [])
        self.assertEqual(files["OUTBOX/orphan/stray.txt"]["referenced_by"], [])

    def test_generated_file_is_attributed_when_issue_note_mentions_its_folder(self) -> None:
        note = self.brain / "WIP" / "area" / "repo" / "PROJ-1 - Example" / "PROJ-1 - Example.md"
        _write(note, ISSUE + "\nOutputs live in OUTBOX/proj-1-run.\n", "2026-03-10")
        result = self.run_collect(date(2026, 3, 9))
        files = {f["path"]: f for f in result["generated_files"]}
        self.assertEqual(files["OUTBOX/proj-1-run/result.log"]["referenced_by"], ["PROJ-1"])
        self.assertEqual(files["OUTBOX/orphan/stray.txt"]["referenced_by"], [])

    # --- attribution against every issue note, touched or not -------------------------------

    def _issue_note(self, folder: str, issue_id: str, text: str = "", day: str = "2026-02-15",
                    root: str = "WIP", work_type: str = "unplanned", status: str = "in-progress") -> Path:
        """An issue note outside the range (dated entries and mtime before 2026-03-09)."""
        body = (
            f"---\ntags: [issue]\nissue_id: {issue_id}\nstatus: {status}\nwork_type: {work_type}\n---\n"
            f"# {issue_id}\n\n## Status\n\n### 2026-01-09: old\n- Old work.\n{text}\n"
        )
        note = self.brain / root / "area" / "repo" / folder / f"{folder}.md"
        return _write(note, body, day)

    def _referenced(self, result: dict[str, object]) -> dict[str, dict[str, object]]:
        return {i["issue_id"]: i for i in result["referenced_issues"]}  # type: ignore[index,union-attr]

    def test_untouched_issue_referenced_by_an_artifact_is_context_not_activity(self) -> None:
        self._issue_note("PROJ-3", "PROJ-3", "Outputs in OUTBOX/orphan.")

        result = self.run_collect(date(2026, 3, 9))

        self.assertEqual({i["issue_id"] for i in result["issues"]}, {"PROJ-1"})
        referenced = self._referenced(result)
        self.assertEqual(list(referenced), ["PROJ-3"])
        self.assertEqual(
            {k: referenced["PROJ-3"][k] for k in ("work_type", "status")},
            {"work_type": "unplanned", "status": "in-progress"},
        )
        self.assertTrue(str(referenced["PROJ-3"]["path"]).endswith("PROJ-3/PROJ-3.md"))
        files = {f["path"]: f for f in result["generated_files"]}
        self.assertEqual(files["OUTBOX/orphan/stray.txt"]["referenced_by"], ["PROJ-3"])

    def test_same_attribution_under_memory_projects_and_with_inclusive_range_edges(self) -> None:
        self._issue_note("PROJ-4", "PROJ-4", "See OUTBOX/edge-start and OUTBOX/edge-end.", root="MEMORY/Projects")
        _write(self.brain / "OUTBOX" / "edge-start" / "a.txt", "x\n", "2026-03-09")
        _write(self.brain / "OUTBOX" / "edge-end" / "b.txt", "x\n", "2026-03-11")
        _write(self.brain / "OUTBOX" / "edge-before" / "c.txt", "x\n", "2026-03-08")

        result = self.run_collect(date(2026, 3, 9), date(2026, 3, 11))

        files = {f["path"]: f["referenced_by"] for f in result["generated_files"]}
        self.assertEqual(files["OUTBOX/edge-start/a.txt"], ["PROJ-4"])
        self.assertEqual(files["OUTBOX/edge-end/b.txt"], ["PROJ-4"])
        self.assertNotIn("OUTBOX/edge-before/c.txt", files)
        self.assertEqual(list(self._referenced(result)), ["PROJ-4"])

    def test_reference_only_in_an_untouched_facet_still_attributes(self) -> None:
        folder = self.brain / "WIP" / "area" / "repo" / "PROJ-5"
        _write(folder / "PROJ-5.md", "---\nissue_id: PROJ-5\nstatus: open\nwork_type: sprint\n---\n# PROJ-5\n", "2026-02-15")
        _write(folder / "proj-5.analysis.md", "---\nissue_id: PROJ-5\n---\nResults: OUTBOX/orphan\n", "2026-02-15")

        result = self.run_collect(date(2026, 3, 9))

        files = {f["path"]: f["referenced_by"] for f in result["generated_files"]}
        self.assertEqual(files["OUTBOX/orphan/stray.txt"], ["PROJ-5"])
        referenced = self._referenced(result)["PROJ-5"]
        self.assertTrue(str(referenced["path"]).endswith("PROJ-5/PROJ-5.md"))
        self.assertEqual(referenced["work_type"], "sprint")

    def test_touched_facet_with_untouched_primary_keeps_its_activity_and_adds_no_reference_only_entry(self) -> None:
        folder = self.brain / "WIP" / "area" / "repo" / "PROJ-6"
        _write(folder / "PROJ-6.md", "---\nissue_id: PROJ-6\nstatus: open\nwork_type: sprint\n---\n# PROJ-6\n", "2026-02-15")
        _write(
            folder / "proj-6.analysis.md",
            "---\nissue_id: PROJ-6\n---\n### 2026-03-10: analysed\n- Found it. See OUTBOX/orphan\n",
            "2026-03-10",
        )

        result = self.run_collect(date(2026, 3, 9))

        issues = {i["issue_id"]: i for i in result["issues"]}
        self.assertIn("PROJ-6", issues)
        self.assertEqual(issues["PROJ-6"]["dated_entries"][0]["date"], "2026-03-10")
        self.assertNotIn("PROJ-6", self._referenced(result))
        files = {f["path"]: f["referenced_by"] for f in result["generated_files"]}
        self.assertEqual(files["OUTBOX/orphan/stray.txt"], ["PROJ-6"])

    def test_touched_primary_referencing_an_artifact_is_not_duplicated_as_context(self) -> None:
        note = self.brain / "WIP" / "area" / "repo" / "PROJ-1 - Example" / "PROJ-1 - Example.md"
        _write(note, ISSUE + "\nOutputs live in OUTBOX/proj-1-run.\n", "2026-03-10")

        result = self.run_collect(date(2026, 3, 9))

        self.assertEqual(result["referenced_issues"], [])

    def test_generic_names_and_prefix_collisions_stay_unattributed(self) -> None:
        self._issue_note("PROJ-7", "PROJ-7", "Mentions result.log and OUTBOX/proj-1-run-old and OUTBOX/proj-1-run.bak.")
        _write(self.brain / "OUTBOX" / "other" / "result.log", "x\n", "2026-03-09")

        result = self.run_collect(date(2026, 3, 9))

        files = {f["path"]: f["referenced_by"] for f in result["generated_files"]}
        self.assertEqual(files["OUTBOX/proj-1-run/result.log"], [])
        self.assertEqual(files["OUTBOX/other/result.log"], [])
        self.assertEqual(result["referenced_issues"], [])

    def test_path_spellings_and_unreferenced_ticket_like_folders(self) -> None:
        _write(self.brain / "OUTBOX" / "my run" / "out file.txt", "x\n", "2026-03-09")
        _write(self.brain / "OUTBOX" / "proj-8-run" / "r.txt", "x\n", "2026-03-09")
        self._issue_note(
            "PROJ-8", "PROJ-8",
            "[[OUTBOX/my run/out file.txt|log]] and [r](OUTBOX/proj-1-run/result.log) and "
            "<OUTBOX/orphan/stray.txt> and OUTBOX/my%20run.",
        )

        result = self.run_collect(date(2026, 3, 9))

        files = {f["path"]: f["referenced_by"] for f in result["generated_files"]}
        self.assertEqual(files["OUTBOX/my run/out file.txt"], ["PROJ-8"])
        self.assertEqual(files["OUTBOX/proj-1-run/result.log"], ["PROJ-8"])
        self.assertEqual(files["OUTBOX/orphan/stray.txt"], ["PROJ-8"])
        self.assertEqual(files["OUTBOX/proj-8-run/r.txt"], [])

    def test_overlapping_scan_dirs_list_a_file_once_with_sorted_distinct_references(self) -> None:
        self._issue_note("PROJ-9", "PROJ-9", "OUTBOX/orphan/stray.txt")
        self._issue_note("PROJ-10", "PROJ-10", "[[OUTBOX/orphan/stray.txt]]")

        result = collector.collect(
            self.brain, date(2026, 3, 9), TODAY, TODAY, ["OUTBOX", "OUTBOX/orphan", "OUTBOX/"]
        )

        paths = [f["path"] for f in result["generated_files"]]
        self.assertEqual(len(paths), len(set(paths)))
        files = {f["path"]: f["referenced_by"] for f in result["generated_files"]}
        self.assertEqual(files["OUTBOX/orphan/stray.txt"], ["PROJ-10", "PROJ-9"])
        self.assertEqual(list(self._referenced(result)), ["PROJ-10", "PROJ-9"])

    def test_untouched_unreferenced_issue_stays_absent(self) -> None:
        self._issue_note("PROJ-11", "PROJ-11", "Nothing about outputs here.")

        result = self.run_collect(date(2026, 3, 9))

        self.assertNotIn("PROJ-11", {i["issue_id"] for i in result["issues"]})
        self.assertEqual(result["referenced_issues"], [])

    def test_empty_work_type_and_conflicting_primaries(self) -> None:
        self._issue_note("PROJ-12", "PROJ-12", "OUTBOX/orphan", work_type="")
        folder = self.brain / "MEMORY" / "Projects" / "area" / "repo" / "PROJ-12"
        _write(
            folder / "PROJ-12.md",
            "---\nissue_id: PROJ-12\nstatus: done\nwork_type: sprint\n---\n# PROJ-12\n",
            "2026-02-15",
        )

        result = self.run_collect(date(2026, 3, 9))

        referenced = self._referenced(result)["PROJ-12"]
        self.assertTrue(str(referenced["path"]).startswith("MEMORY/Projects/"))
        self.assertTrue(any("PROJ-12" in w and "disagree" in w for w in result["warnings"]))  # type: ignore[union-attr]

    def test_collection_never_writes_to_the_brain(self) -> None:
        def snapshot() -> dict[str, tuple[float, str]]:
            return {
                str(p): (p.stat().st_mtime, p.read_text(encoding="utf-8"))
                for p in sorted(self.brain.rglob("*"))
                if p.is_file()
            }

        before = snapshot()
        self.run_collect(date(2026, 3, 6))
        self.assertEqual(snapshot(), before)

    def test_invalid_ranges_raise(self) -> None:
        with self.assertRaises(ValueError):
            self.run_collect(date(2026, 3, 12))
        empty = Path(self._tmp.name) / "empty"
        (empty / "JOURNAL").mkdir(parents=True)
        with self.assertRaises(ValueError):
            collector.collect(empty, None, TODAY, TODAY)

    def test_cli_prints_json_and_reports_errors_with_exit_code_2(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = collector.main(["--brain-root", str(self.brain), "--today", "2026-03-11", "--from", "2026-03-09"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["range"]["from"], "2026-03-09")

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = collector.main(
                ["--brain-root", str(self.brain), "--today", "2026-03-11", "--from", "2026-03-12"]
            )
        self.assertEqual(code, 2)
        self.assertIn("is after --to", err.getvalue())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "brain" / "scripts"
SCRIPT = SCRIPTS / "session_close.py"
MODEL_ROOT = REPO_ROOT / "model"
sys.path.insert(0, str(SCRIPTS))

from session_transcripts import (  # noqa: E402
    HAS_ACTIVITY,
    NO_ACTIVITY,
    UNVERIFIED,
    classify_session_activity,
)


def run(*args: str, claude_config: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(claude_config or "/nonexistent-claude-config")
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def git(brain: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=brain, text=True, capture_output=True, check=False)


def write_transcript(
    config: Path,
    session_id: str,
    prompts: int,
    tool_uses: int,
    tool_name: str = "Bash",
    reply_chars: int = 0,
) -> None:
    project = config / "projects" / "-some-project"
    project.mkdir(parents=True, exist_ok=True)
    entries = [
        {"type": "user", "message": {"role": "user", "content": f"prompt {n}"}}
        for n in range(prompts)
    ]
    blocks: list[dict] = [{"type": "tool_use", "name": tool_name} for _ in range(tool_uses)]
    if reply_chars:
        blocks.append({"type": "text", "text": "x" * reply_chars})
    entries.append({"type": "assistant", "message": {"content": blocks}})
    entries.append(
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}}
    )
    (project / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8"
    )


class EmptyNoteFixture(unittest.TestCase):
    def setUp(self) -> None:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        self.root = Path(raw.name)
        self.brain = self.root / "brain"
        self.brain.mkdir()
        self.config = self.root / "claude"
        (self.brain / "_COMMON").symlink_to(MODEL_ROOT, target_is_directory=True)
        self.assertEqual(git(self.brain, "init", "-q").returncode, 0)
        git(self.brain, "config", "user.email", "tests@example.invalid")
        git(self.brain, "config", "user.name", "agent-brain tests")

    def add_note(
        self, session_id: str, age_days: int, body: str = "", status: str = "open"
    ) -> Path:
        day = date.today() - timedelta(days=age_days)
        note = self.brain / "WIP" / "SESSIONS" / f"{day}-session-{session_id}-topic.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            "---\ntags: [session, wip]\n---\n"
            f"# Session {session_id}\n\n"
            f"## State\n- Status: {status}\n\n"
            "## Resume command\n"
            f"- `cd /repo && claude --resume {session_id}`\n\n"
            f"## Current objective\n{body}\n"
            "## Consolidation checklist\n"
            "- [ ] `WIP/WIP.md` updated if needed\n"
            "- [ ] Session ID written in daily note\n",
            encoding="utf-8",
        )
        git(self.brain, "add", str(note.relative_to(self.brain)))
        self.assertEqual(git(self.brain, "commit", "-qm", "fixture").returncode, 0)
        return note


class EmptyNoteFastPathTests(EmptyNoteFixture):
    def test_empty_note_consolidates_without_checklist_reasons(self) -> None:
        note = self.add_note("ses-empty", 5)

        result = run("--brain-root", str(self.brain), "--apply", "consolidate", "ses-empty")

        content = note.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("empty note: closing-gate checklist skipped", result.stdout)
        self.assertIn("- Status: consolidated", content)
        self.assertIn("- Closed reason: never worked", content)

    def test_empty_note_dry_run_does_not_mutate(self) -> None:
        note = self.add_note("ses-empty", 5)
        before = note.read_text(encoding="utf-8")

        result = run("--brain-root", str(self.brain), "consolidate", "ses-empty")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("would add: never-worked reason line", result.stdout)
        self.assertEqual(note.read_text(encoding="utf-8"), before)

    def test_empty_note_with_transcript_activity_does_not_take_the_fast_path(self) -> None:
        note = self.add_note("ses-busy", 5)
        write_transcript(self.config, "ses-busy", prompts=1, tool_uses=40)

        result = run(
            "--brain-root", str(self.brain), "--apply", "consolidate", "ses-busy",
            claude_config=self.config,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("shows activity", result.stderr)
        self.assertIn("closing gate incomplete", result.stderr)
        self.assertIn("- Status: open", note.read_text(encoding="utf-8"))

    def test_empty_note_without_transcript_still_takes_the_fast_path(self) -> None:
        note = self.add_note("ses-codex", 5)

        result = run("--brain-root", str(self.brain), "--apply", "consolidate", "ses-codex")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- Status: consolidated", note.read_text(encoding="utf-8"))

    def test_note_with_content_still_hits_the_gate(self) -> None:
        note = self.add_note("ses-worked", 5, body="- reviewed the migration\n")

        result = run("--brain-root", str(self.brain), "--apply", "consolidate", "ses-worked")

        self.assertEqual(result.returncode, 1)
        self.assertIn("closing gate incomplete", result.stderr)
        self.assertIn("- Status: open", note.read_text(encoding="utf-8"))


class CloseEmptyTests(EmptyNoteFixture):
    def test_lists_only_old_empty_open_notes_with_evidence(self) -> None:
        self.add_note("ses-quiet", 6)
        self.add_note("ses-busy", 6)
        self.add_note("ses-young", 1)
        self.add_note("ses-worked", 6, body="- real work\n")
        self.add_note("ses-done", 6, status="consolidated")
        self.add_note("ses-codex", 6)
        write_transcript(self.config, "ses-quiet", prompts=1, tool_uses=3)
        write_transcript(self.config, "ses-busy", prompts=1, tool_uses=40)

        result = run("--brain-root", str(self.brain), "close-empty", claude_config=self.config)

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = {line.split("id=")[1].split()[0]: line for line in result.stdout.splitlines() if "id=" in line}
        self.assertEqual(set(lines), {"ses-quiet", "ses-busy", "ses-codex"})
        self.assertIn(NO_ACTIVITY, lines["ses-quiet"])
        self.assertIn(HAS_ACTIVITY, lines["ses-busy"])
        self.assertIn(UNVERIFIED, lines["ses-codex"])

    def test_min_age_days_is_configurable(self) -> None:
        self.add_note("ses-young", 1)

        default = run("--brain-root", str(self.brain), "close-empty", claude_config=self.config)
        relaxed = run(
            "--brain-root", str(self.brain), "close-empty", "--min-age-days", "1",
            claude_config=self.config,
        )

        self.assertIn("- none", default.stdout)
        self.assertIn("id=ses-young", relaxed.stdout)

    def test_apply_refuses_note_with_activity(self) -> None:
        note = self.add_note("ses-busy", 6)
        write_transcript(self.config, "ses-busy", prompts=1, tool_uses=40)

        result = run(
            "--brain-root", str(self.brain), "--apply", "close-empty", "ses-busy",
            claude_config=self.config,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("shows activity outside its note", result.stderr)
        self.assertTrue(note.exists())
        self.assertIn("- Status: open", note.read_text(encoding="utf-8"))

    def test_apply_refuses_unverified_note_without_flag(self) -> None:
        note = self.add_note("ses-codex", 6)

        result = run(
            "--brain-root", str(self.brain), "--apply", "close-empty", "ses-codex",
            claude_config=self.config,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("--include-unverified", result.stderr)
        self.assertTrue(note.exists())

    def test_apply_closes_and_archives_note_without_activity(self) -> None:
        note = self.add_note("ses-quiet", 6)
        write_transcript(self.config, "ses-quiet", prompts=1, tool_uses=3)

        result = run(
            "--brain-root", str(self.brain), "--apply", "close-empty", "ses-quiet",
            claude_config=self.config,
        )

        archived = self.brain / "QUARANTINE" / "TRASH" / note.name
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(note.exists())
        content = archived.read_text(encoding="utf-8")
        self.assertIn("- Status: consolidated", content)
        self.assertIn("- Closed reason: never worked", content)

    def test_apply_closes_unverified_note_with_flag(self) -> None:
        note = self.add_note("ses-codex", 6)

        result = run(
            "--brain-root", str(self.brain), "--apply", "close-empty", "--include-unverified",
            "ses-codex", claude_config=self.config,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(note.exists())

    def test_apply_archives_only_the_validated_note_when_ids_repeat_across_days(self) -> None:
        old = self.add_note("ses-dup", 10)
        recent = self.add_note("ses-dup", 1, body="- still working\n")
        write_transcript(self.config, "ses-dup", prompts=1, tool_uses=2)

        result = run(
            "--brain-root", str(self.brain), "--apply", "close-empty", "ses-dup",
            claude_config=self.config,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertIn("- Status: open", recent.read_text(encoding="utf-8"))

    def test_apply_refuses_unknown_id(self) -> None:
        self.add_note("ses-quiet", 6)

        result = run(
            "--brain-root", str(self.brain), "--apply", "close-empty", "ses-missing",
            claude_config=self.config,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("matches 0 candidates", result.stderr)

    def test_dry_run_with_ids_does_not_mutate(self) -> None:
        note = self.add_note("ses-quiet", 6)
        write_transcript(self.config, "ses-quiet", prompts=1, tool_uses=3)

        result = run(
            "--brain-root", str(self.brain), "close-empty", "ses-quiet",
            claude_config=self.config,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(note.exists())
        self.assertIn("- Status: open", note.read_text(encoding="utf-8"))


class TranscriptClassifierTests(unittest.TestCase):
    def classify(self, setup) -> str:
        with tempfile.TemporaryDirectory() as raw:
            config = Path(raw)
            setup(config)
            old = os.environ.get("CLAUDE_CONFIG_DIR")
            os.environ["CLAUDE_CONFIG_DIR"] = raw
            try:
                return classify_session_activity("sid")[0]
            finally:
                if old is None:
                    del os.environ["CLAUDE_CONFIG_DIR"]
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = old

    def test_classification_levels(self) -> None:
        cases = {
            "quiet": (lambda c: write_transcript(c, "sid", prompts=1, tool_uses=3), NO_ACTIVITY),
            "talkative": (lambda c: write_transcript(c, "sid", prompts=3, tool_uses=0), HAS_ACTIVITY),
            "eight calls": (lambda c: write_transcript(c, "sid", prompts=1, tool_uses=8), NO_ACTIVITY),
            "nine calls": (lambda c: write_transcript(c, "sid", prompts=1, tool_uses=9), HAS_ACTIVITY),
            "single edit": (
                lambda c: write_transcript(c, "sid", prompts=1, tool_uses=1, tool_name="Edit"),
                HAS_ACTIVITY,
            ),
            "mcp call": (
                lambda c: write_transcript(
                    c, "sid", prompts=1, tool_uses=1, tool_name="mcp__x__post"
                ),
                HAS_ACTIVITY,
            ),
            "long reply without tools": (
                lambda c: write_transcript(c, "sid", prompts=1, tool_uses=0, reply_chars=2500),
                HAS_ACTIVITY,
            ),
            "short reply": (
                lambda c: write_transcript(c, "sid", prompts=1, tool_uses=0, reply_chars=200),
                NO_ACTIVITY,
            ),
            "absent": (lambda c: None, UNVERIFIED),
        }
        for name, (setup, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.classify(setup), expected)

    def test_unreadable_transcripts_are_unverified(self) -> None:
        def write(content: str):
            def setup(config: Path) -> None:
                project = config / "projects" / "-p"
                project.mkdir(parents=True)
                (project / "sid.jsonl").write_text(content, encoding="utf-8")

            return setup

        cases = {
            "empty file": "",
            "garbage": "not json at all\n{broken\n",
            "truncated": '{"type": "user", "message": {"content": "hi"',
            "unknown schema": '{"kind": "other"}\n[1, 2]\n',
        }
        for name, content in cases.items():
            with self.subTest(name):
                self.assertEqual(self.classify(write(content)), UNVERIFIED)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.support.session_open_test_support import (
    session_open,
    snapshot_tree,
)

class SessionOpenRaceMixin:
    def test_wip_symlink_substitution_during_apply_cannot_escape(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            outside = root / "outside"
            brain.mkdir()
            outside.mkdir()
            self.attach_current_model(brain)
            (brain / "WIP").mkdir()
            (outside / "sentinel.txt").write_text("unchanged\n", encoding="utf-8")
            templates = brain / "TEMPLATES"
            templates.mkdir()
            template = templates / "TEMPLATE.wip-session.common.md"
            template.write_text(
                "# Session <date> / <topic> / <id>\n\n"
                "## Resume command\n- placeholder\n",
                encoding="utf-8",
            )
            today = datetime.now().strftime("%Y-%m-%d")
            daily = brain / "JOURNAL" / f"{today}.md"
            daily.parent.mkdir()
            daily.write_text("# Sessions\n\n# Actions\n", encoding="utf-8")
            outside_before = snapshot_tree(outside)
            actual_instantiate = session_open.instantiate_session_template

            def substitute_wip(*args: str | Path) -> str:
                content = actual_instantiate(*args)
                (brain / "WIP").rename(brain / "WIP-original")
                (brain / "WIP").symlink_to(outside, target_is_directory=True)
                return content

            argv = [
                "session_open.py",
                "--brain-root",
                str(brain),
                "--session-id",
                "session-race",
                "--runtime",
                "codex",
                "--cwd",
                "/workspace/project",
                "--apply",
            ]
            with (
                patch("sys.argv", argv),
                patch(
                    "session_open.instantiate_session_template",
                    side_effect=substitute_wip,
                ),
            ):
                result = session_open.main()

            self.assertNotEqual(result, 0)
            self.assertEqual(snapshot_tree(outside), outside_before)

    def test_daily_symlink_substitution_during_apply_cannot_escape(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            outside = root / "outside"
            brain.mkdir()
            outside.mkdir()
            self.attach_current_model(brain)
            templates = brain / "TEMPLATES"
            templates.mkdir()
            (templates / "TEMPLATE.wip-session.common.md").write_text(
                "# Session <date> / <topic> / <id>\n\n"
                "## Resume command\n- placeholder\n",
                encoding="utf-8",
            )
            today = datetime.now().strftime("%Y-%m-%d")
            daily = brain / "JOURNAL" / f"{today}.md"
            daily.parent.mkdir()
            original_daily = "# Sessions\n\n# Actions\n* unchanged\n"
            daily.write_text(original_daily, encoding="utf-8")
            external = outside / "daily.md"
            external.write_text("# Sessions\n\n# External\n* unchanged\n", encoding="utf-8")
            external_before = external.read_bytes()
            displaced_daily = daily.with_name(f"{today}-original.md")
            actual_upsert = session_open.upsert_sessions_entry

            def substitute_daily(
                daily_path: Path,
                entry: str,
                session_id: str,
                apply: bool,
                *,
                safe_root: Path | None = None,
            ) -> str:
                if apply:
                    daily.rename(displaced_daily)
                    daily.symlink_to(external)
                return actual_upsert(
                    daily_path,
                    entry,
                    session_id,
                    apply,
                    safe_root=safe_root,
                )

            argv = [
                "session_open.py",
                "--brain-root",
                str(brain),
                "--session-id",
                "session-daily-race",
                "--runtime",
                "codex",
                "--cwd",
                "/workspace/project",
                "--apply",
            ]
            with (
                patch("sys.argv", argv),
                patch(
                    "session_open.upsert_sessions_entry",
                    side_effect=substitute_daily,
                ),
            ):
                result = session_open.main()

            session_notes = list((brain / "WIP" / "SESSIONS").glob("*.md"))
            self.assertNotEqual(result, 0)
            self.assertEqual(external.read_bytes(), external_before)
            self.assertEqual(displaced_daily.read_text(encoding="utf-8"), original_daily)
            self.assertEqual(session_notes, [])

    def test_programming_exception_rolls_back_new_session_note_and_propagates(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            self.attach_current_model(brain)
            templates = brain / "TEMPLATES"
            templates.mkdir()
            (templates / "TEMPLATE.wip-session.common.md").write_text(
                "# Session <date> / <topic> / <id>\n\n"
                "## Resume command\n- placeholder\n",
                encoding="utf-8",
            )
            today = datetime.now().strftime("%Y-%m-%d")
            daily = brain / "JOURNAL" / f"{today}.md"
            daily.parent.mkdir()
            daily.write_text("# Sessions\n\n# Actions\n", encoding="utf-8")
            before = snapshot_tree(brain)
            actual_upsert = session_open.upsert_sessions_entry

            def fail_apply(
                daily_path: Path,
                entry: str,
                session_id: str,
                apply: bool,
                *,
                safe_root: Path | None = None,
            ) -> str:
                if apply:
                    raise TypeError("injected programming failure")
                return actual_upsert(
                    daily_path,
                    entry,
                    session_id,
                    apply=False,
                    safe_root=safe_root,
                )

            argv = [
                "session_open.py",
                "--brain-root",
                str(brain),
                "--session-id",
                "session-type-error",
                "--runtime",
                "codex",
                "--cwd",
                "/workspace/project",
                "--apply",
            ]
            propagated: TypeError | None = None
            traceback_present = False
            with (
                patch("sys.argv", argv),
                patch("session_open.upsert_sessions_entry", side_effect=fail_apply),
            ):
                try:
                    session_open.main()
                except TypeError as exc:
                    propagated = exc
                    traceback_present = exc.__traceback__ is not None

            self.assertIsNotNone(propagated)
            self.assertEqual(str(propagated), "injected programming failure")
            self.assertTrue(traceback_present)
            self.assertEqual(snapshot_tree(brain), before)

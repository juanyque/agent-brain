from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import session_open_fs
from tests.support.session_open_test_support import session_open


class SessionOpenToctouMixin:
    def test_session_note_creation_failure_parent_swap_preserves_external_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            note = brain / "WIP" / "SESSIONS" / "created.md"
            outside = root / "outside"
            external_sessions = outside / "SESSIONS"
            external_sessions.mkdir(parents=True)
            actual_open = os.open
            swapped = False

            def swap_parent_then_fail_note_open(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal swapped
                if path == note.name and flags & os.O_CREAT:
                    (brain / "WIP").rename(brain / "WIP-original")
                    (brain / "WIP").symlink_to(outside, target_is_directory=True)
                    swapped = True
                    raise OSError("injected session-note creation failure")
                if dir_fd is None:
                    return actual_open(path, flags, mode)
                return actual_open(path, flags, mode, dir_fd=dir_fd)

            with patch("os.open", side_effect=swap_parent_then_fail_note_open):
                with self.assertRaises(OSError):
                    session_open_fs._create_session_note_no_follow(
                        brain,
                        note,
                        "created\\n",
                    )

            self.assertTrue(swapped)
            self.assertTrue(
                external_sessions.exists(),
                "creation cleanup followed a swapped parent and removed external directory",
            )

    def test_rollback_parent_swap_cannot_delete_external_session_note(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            sessions = brain / "WIP" / "SESSIONS"
            sessions.mkdir(parents=True)
            note = sessions / "created.md"
            note.write_text("created\n", encoding="utf-8")
            outside = root / "outside"
            (outside / "SESSIONS").mkdir(parents=True)
            sentinel = outside / "SESSIONS" / note.name
            sentinel.write_text("sentinel\n", encoding="utf-8")
            actual_unlink = os.unlink
            swapped = False

            def swap_parent_then_unlink(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                *,
                dir_fd: int | None = None,
            ) -> None:
                nonlocal swapped
                if not swapped:
                    (brain / "WIP").rename(brain / "WIP-original")
                    (brain / "WIP").symlink_to(outside, target_is_directory=True)
                    swapped = True
                if dir_fd is None:
                    actual_unlink(path)
                else:
                    actual_unlink(path, dir_fd=dir_fd)

            with patch("os.unlink", side_effect=swap_parent_then_unlink):
                errors = session_open_fs._rollback_created_session_note(
                    brain,
                    note,
                    [],
                )

            self.assertTrue(swapped)
            self.assertEqual(errors, [])
            self.assertTrue(
                sentinel.exists(),
                "rollback followed a swapped parent and deleted external content",
            )

    def test_post_registration_daily_symlink_cannot_validate_external_content(
        self,
    ) -> None:
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
            session_id = "session-post-registration-race"
            today = datetime.now().strftime("%Y-%m-%d")
            daily = brain / "JOURNAL" / f"{today}.md"
            daily.parent.mkdir()
            daily.write_text("# Sessions\n\n# Actions\n", encoding="utf-8")
            displaced_daily = daily.with_name(f"{today}-registered.md")
            note_stem = f"{today}-session-{session_id}-project"
            command = f"cd /workspace/project && codex resume {session_id}"
            external = outside / "daily.md"
            external.write_text(
                f"# Sessions\n- `{command}` — project. "
                f"Session note: [[{note_stem}]].\n\n# Actions\n",
                encoding="utf-8",
            )
            external_before = external.read_bytes()
            actual_upsert = session_open.upsert_sessions_entry

            def substitute_after_registration(
                daily_path: Path,
                entry: str,
                current_session_id: str,
                apply: bool,
                *,
                safe_root: Path | None = None,
            ) -> str:
                action = actual_upsert(
                    daily_path,
                    entry,
                    current_session_id,
                    apply,
                    safe_root=safe_root,
                )
                if apply:
                    daily.rename(displaced_daily)
                    daily.symlink_to(external)
                return action

            argv = [
                "session_open.py",
                "--brain-root",
                str(brain),
                "--session-id",
                session_id,
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
                    side_effect=substitute_after_registration,
                ),
            ):
                result = session_open.main()

            self.assertNotEqual(
                result,
                0,
                "external daily content incorrectly validated transaction success",
            )
            self.assertEqual(external.read_bytes(), external_before)

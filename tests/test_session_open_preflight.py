from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "brain" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from session_open_preflight import collect_preflight  # noqa: E402


class SessionOpenPreflightTests(unittest.TestCase):
    def test_preflight_is_advisory_and_counts_peers_without_ownership(self) -> None:
        with patch(
            "session_open_preflight.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="/repo\nmain\n", stderr=""
                ),
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=b" M file.md\0?? new.md\0", stderr=b""
                ),
            ],
        ):
            result = collect_preflight(
                cwd="/repo",
                session_id="ses-current",
                open_sessions=(
                    "WIP/SESSIONS/2026-session-ses-current-topic.md",
                    "WIP/SESSIONS/2026-session-ses-peer-topic.md",
                ),
                rollover_pending=True,
            )

        self.assertEqual(result.git_root, "/repo")
        self.assertEqual(result.branch, "main")
        self.assertEqual(result.changed_entries, 2)
        self.assertEqual(result.peer_sessions, 1)
        self.assertTrue(result.rollover_pending)

    def test_non_repository_cwd_is_not_a_session_start_failure(self) -> None:
        with patch(
            "session_open_preflight.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=128, stdout="", stderr="not a repository"
            ),
        ):
            result = collect_preflight(
                cwd="/not/a/repository",
                session_id="ses-current",
                open_sessions=(),
                rollover_pending=False,
            )

        self.assertIsNone(result.git_root)
        self.assertTrue(result.git_unavailable)
        self.assertEqual(result.peer_sessions, 0)

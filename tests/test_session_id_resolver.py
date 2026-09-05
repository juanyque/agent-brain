from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "brain" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from resolve_session_id import (  # noqa: E402
    EXIT_ERROR,
    EXIT_RESOLVED,
    EXIT_UNRESOLVED,
    EXIT_UNSUPPORTED,
    candidates,
    install_plugin,
    parse_launch_session,
    probe,
)

CWD = "/fake/project"

SESSION_DDL = """
CREATE TABLE session (
    id text PRIMARY KEY,
    directory text NOT NULL,
    title text NOT NULL,
    time_updated integer NOT NULL
)
"""

PART_DDL = """
CREATE TABLE part (
    id text PRIMARY KEY,
    session_id text NOT NULL,
    time_updated integer NOT NULL
)
"""


def build_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.executescript(SESSION_DDL + ";" + PART_DDL + ";")
    return connection


def seed_session(
    connection: sqlite3.Connection,
    session_id: str,
    directory: str,
    title: str,
    last_part_ms: int,
    *,
    extra_part_ms: int | None = None,
) -> None:
    connection.execute(
        "INSERT INTO session (id, directory, title, time_updated) VALUES (?,?,?,?)",
        (session_id, directory, title, last_part_ms),
    )
    connection.execute(
        "INSERT INTO part (id, session_id, time_updated) VALUES (?,?,?)",
        (f"prt_{session_id}_a", session_id, last_part_ms),
    )
    if extra_part_ms is not None:
        connection.execute(
            "INSERT INTO part (id, session_id, time_updated) VALUES (?,?,?)",
            (f"prt_{session_id}_b", session_id, extra_part_ms),
        )
    connection.commit()


class ParseLaunchSessionTests(unittest.TestCase):
    def test_short_flag_with_value(self):
        self.assertEqual(
            parse_launch_session(["opencode", "-s", "ses_1"]), "ses_1"
        )

    def test_long_flag_with_value(self):
        self.assertEqual(
            parse_launch_session(["opencode", "--session", "ses_2"]), "ses_2"
        )

    def test_long_flag_equals_form(self):
        self.assertEqual(
            parse_launch_session(["opencode", "--session=ses_3"]), "ses_3"
        )

    def test_short_flag_attached_form(self):
        self.assertEqual(parse_launch_session(["opencode", "-sses_4"]), "ses_4")

    def test_flag_with_missing_value(self):
        self.assertIsNone(parse_launch_session(["opencode", "-s"]))

    def test_flag_followed_by_another_flag(self):
        self.assertIsNone(parse_launch_session(["opencode", "-s", "--pure"]))

    def test_unrelated_flag_is_ignored(self):
        self.assertIsNone(
            parse_launch_session(["opencode", "--session-dir", "/tmp"])
        )


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "opencode.db"
        self.now = 1_788_000_000_000

    def tearDown(self):
        self.tmp.cleanup()

    def test_clear_winner_in_cwd(self):
        connection = build_db(self.db_path)
        seed_session(connection, "ses_win", CWD, "live", self.now - 2_000)
        seed_session(
            connection, "ses_old", CWD, "idle peer", self.now - 300_000
        )
        seed_session(
            connection,
            "ses_other_dir",
            "/other/project",
            "live elsewhere",
            self.now - 1_000,
        )
        connection.close()
        winner, evidence = probe(self.db_path, CWD, self.now, 900, 5)
        self.assertEqual(winner, "ses_win")
        self.assertEqual(evidence["winner"]["session_id"], "ses_win")

    def test_ambiguous_runner_up_blocks_resolution(self):
        connection = build_db(self.db_path)
        seed_session(connection, "ses_a", CWD, "a", self.now - 2_000)
        seed_session(connection, "ses_b", CWD, "b", self.now - 4_000)
        connection.close()
        winner, evidence = probe(self.db_path, CWD, self.now, 900, 5)
        self.assertIsNone(winner)
        self.assertIn("ambiguous", evidence["probe_error"])

    def test_stale_winner_is_rejected(self):
        connection = build_db(self.db_path)
        seed_session(connection, "ses_stale", CWD, "old", self.now - 3_600_000)
        connection.close()
        winner, evidence = probe(self.db_path, CWD, self.now, 900, 5)
        self.assertIsNone(winner)
        self.assertIn("stale", evidence["probe_error"])

    def test_no_sessions_in_cwd(self):
        connection = build_db(self.db_path)
        seed_session(connection, "ses_x", "/elsewhere", "x", self.now - 1_000)
        connection.close()
        winner, evidence = probe(self.db_path, CWD, self.now, 900, 5)
        self.assertIsNone(winner)
        self.assertIn("no sessions", evidence["probe_error"])

    def test_schema_drift_degrades_gracefully(self):
        connection = sqlite3.connect(self.db_path)
        connection.executescript("CREATE TABLE unrelated (id text);")
        connection.close()
        winner, evidence = probe(self.db_path, CWD, self.now, 900, 5)
        self.assertIsNone(winner)
        self.assertIn("schema drift", evidence["probe_error"])

    def test_missing_db_file_degrades_gracefully(self):
        winner, evidence = probe(
            Path(self.tmp.name) / "nope.db", CWD, self.now, 900, 5
        )
        self.assertIsNone(winner)
        self.assertIn("probe_error", evidence)

    def test_runner_up_in_other_directory_does_not_block(self):
        connection = build_db(self.db_path)
        seed_session(connection, "ses_win", CWD, "live", self.now - 2_000)
        seed_session(
            connection, "ses_peer", "/other/project", "peer", self.now - 2_500
        )
        connection.close()
        winner, _ = probe(self.db_path, CWD, self.now, 900, 5)
        self.assertEqual(winner, "ses_win")


class CandidatesTests(unittest.TestCase):
    def test_directory_filter_and_order(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            db_path = Path(tmp.name) / "opencode.db"
            connection = build_db(db_path)
            seed_session(connection, "ses_new", CWD, "newer", 2_000)
            seed_session(connection, "ses_old", CWD, "older", 1_000)
            seed_session(connection, "ses_out", "/other", "out", 3_000)
            connection.close()
            found = candidates(db_path, CWD, 8)
            self.assertEqual(
                [entry["session_id"] for entry in found],
                ["ses_new", "ses_old"],
            )
        finally:
            tmp.cleanup()


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str, env_extra: dict[str, str] | None = None):
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("OPENCODE_SESSION_ID", "OPENCODE_PID")
        }
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "resolve_session_id.py"), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_plugin_env_signal_wins(self):
        result = self.run_cli(
            "--runtime", "opencode", env_extra={"OPENCODE_SESSION_ID": "ses_env"}
        )
        self.assertEqual(result.returncode, EXIT_RESOLVED)
        self.assertIn('"ses_env"', result.stdout)
        self.assertIn('"plugin_env"', result.stdout)

    def test_unsupported_runtime(self):
        result = self.run_cli("--runtime", "claude")
        self.assertEqual(result.returncode, EXIT_UNSUPPORTED)

    def test_unresolved_emits_candidates_and_exit_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "opencode.db"
            connection = build_db(db_path)
            seed_session(
                connection, "ses_z", str(Path(tmp)), "z", 1
            )
            connection.close()
            result = self.run_cli(
                "--runtime", "opencode", "--cwd", tmp, "--db-path", str(db_path)
            )
            self.assertEqual(result.returncode, EXIT_UNRESOLVED)
            self.assertIn('"ask_user": true', result.stdout)
            self.assertIn("ses_z", result.stdout)

    def test_install_plugin_is_idempotent_guarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"OPENCODE_CONFIG_DIR": str(Path(tmp) / "opencode-config")}
            first = self.run_cli("--install-plugin", env_extra=env)
            self.assertEqual(first.returncode, EXIT_RESOLVED)
            target = Path(env["OPENCODE_CONFIG_DIR"]) / "plugins" / "brain-session-env.js"
            self.assertTrue(target.is_file())
            second = self.run_cli("--install-plugin", env_extra=env)
            self.assertEqual(second.returncode, EXIT_ERROR)
            forced = self.run_cli(
                "--install-plugin", "--force", env_extra=env
            )
            self.assertEqual(forced.returncode, EXIT_RESOLVED)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Resolve the current OpenCode session id deterministically.

Chain (first hit wins):
  1. plugin_env     — $OPENCODE_SESSION_ID, injected by the brain-session-env
                      plugin (opencode `shell.env` hook) into every shell run.
  2. launch_flag    — `-s <id>` / `--session <id>` / `--session=<id>` in the
                      command line of $OPENCODE_PID.
  3. liveness_probe — the session owning the newest `part` write in the
                      OpenCode SQLite DB, restricted to --cwd, requiring
                      recency (--max-age-seconds) and a clear lead over the
                      same-directory runner-up (--margin-seconds).
  4. unresolved     — exit 3; stdout carries candidates for the ask-the-user
                      fallback. Never infer by list order.

Exit codes: 0 resolved · 3 unresolved (candidates emitted) · 2 error ·
4 unsupported runtime. Stdout is always a single JSON object.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sqlite3
import sys
import time
from pathlib import Path

DEFAULT_MAX_AGE_SECONDS = 900
DEFAULT_MARGIN_SECONDS = 5
CANDIDATE_LIMIT = 8

EXIT_RESOLVED = 0
EXIT_ERROR = 2
EXIT_UNRESOLVED = 3
EXIT_UNSUPPORTED = 4

SUPPORTED_RUNTIMES = ("opencode",)


def emit(payload: dict, code: int) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code


def parse_launch_session(argv: list[str]) -> str | None:
    """Extract the session id from an opencode argv list (yargs forms)."""
    for index, token in enumerate(argv):
        if token in ("-s", "--session"):
            if index + 1 < len(argv):
                value = argv[index + 1]
                if value and not value.startswith("-"):
                    return value
        elif token.startswith("--session="):
            value = token.split("=", 1)[1]
            if value:
                return value
        else:
            attached = re.fullmatch(r"-s(\S+)", token)
            if attached and not attached.group(1).startswith("-"):
                return attached.group(1)
    return None


def ps_command_line(pid: str) -> list[str] | None:
    try:
        result = subprocess.run(
            ["ps", "-p", pid, "-o", "command="],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip().split()


def discover_db_path(override: str | None) -> Path | None:
    if override:
        path = Path(override).expanduser()
        return path if path.is_file() else None
    try:
        result = subprocess.run(
            ["opencode", "db", "path"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            output_lines = (result.stdout or "").strip().splitlines()
            if output_lines:
                candidate = Path(output_lines[-1].strip())
                if candidate.is_file():
                    return candidate
    except (OSError, subprocess.SubprocessError, IndexError):
        pass
    fallback = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
    return fallback if fallback.is_file() else None


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)


def probe(
    db_path: Path,
    cwd: str,
    now_ms: int,
    max_age_seconds: int,
    margin_seconds: int,
) -> tuple[str | None, dict]:
    """Liveness probe: newest `part` write wins within cwd, with margin."""
    evidence: dict = {"probe_db": str(db_path)}
    try:
        connection = _connect_readonly(db_path)
    except sqlite3.Error as error:
        evidence["probe_error"] = f"open failed: {error}"
        return None, evidence
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not {"session", "part"} <= tables:
            evidence["probe_error"] = "schema drift: session/part tables missing"
            return None, evidence
        rows = connection.execute(
            """
            SELECT p.session_id, s.directory, s.title, MAX(p.time_updated) AS last_ms
            FROM part p JOIN session s ON s.id = p.session_id
            GROUP BY p.session_id
            ORDER BY last_ms DESC
            LIMIT 50
            """
        ).fetchall()
    except sqlite3.Error as error:
        evidence["probe_error"] = f"query failed: {error}"
        return None, evidence
    finally:
        connection.close()

    cwd_real = os.path.realpath(cwd)
    in_cwd = []
    for session_id, directory, title, last_ms in rows:
        # OpenCode stores the launch-time path verbatim; compare as-is first
        # and fall back to realpath so symlinked launch dirs still match.
        if directory != cwd and os.path.realpath(directory) != cwd_real:
            continue
        in_cwd.append((session_id, title, int(last_ms)))
    evidence["sessions_in_cwd"] = len(in_cwd)
    if not in_cwd:
        evidence["probe_error"] = f"no sessions with directory == {cwd}"
        return None, evidence

    winner_id, winner_title, winner_ms = in_cwd[0]
    age_seconds = max(0, (now_ms - winner_ms) // 1000)
    evidence["winner"] = {
        "session_id": winner_id,
        "title": winner_title,
        "age_seconds": age_seconds,
    }
    if age_seconds > max_age_seconds:
        evidence["probe_error"] = (
            f"winner is stale: {age_seconds}s old (max {max_age_seconds}s)"
        )
        return None, evidence

    runner = next(
        (entry for entry in in_cwd[1:] if entry[0] != winner_id), None
    )
    if runner:
        lead_ms = winner_ms - runner[2]
        evidence["runner_up"] = {
            "session_id": runner[0],
            "lead_ms": lead_ms,
        }
        if lead_ms < margin_seconds * 1000:
            evidence["probe_error"] = (
                f"ambiguous: lead {lead_ms}ms < margin {margin_seconds * 1000}ms"
            )
            return None, evidence
    return winner_id, evidence


def candidates(db_path: Path, cwd: str, limit: int) -> list[dict]:
    try:
        connection = _connect_readonly(db_path)
    except sqlite3.Error:
        return []
    try:
        rows = connection.execute(
            """
            SELECT id, title, time_updated, directory
            FROM session
            WHERE directory = ?
            ORDER BY time_updated DESC
            LIMIT ?
            """,
            (cwd, limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    return [
        {
            "session_id": session_id,
            "title": title,
            "updated_ms": int(updated_ms),
            "directory": directory,
        }
        for session_id, title, updated_ms, directory in rows
    ]


def plugin_source_path(script_path: Path) -> Path:
    return script_path.parent.parent / "plugins" / "brain-session-env.js"


def install_plugin(script_path: Path, force: bool) -> int:
    source = plugin_source_path(script_path)
    if not source.is_file():
        return emit(
            {"error": f"plugin source not found: {source}"}, EXIT_ERROR
        )
    config_root = os.environ.get(
        "OPENCODE_CONFIG_DIR", str(Path.home() / ".config" / "opencode")
    )
    target_dir = Path(config_root).expanduser() / "plugins"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    if target.exists() and not force:
        return emit(
            {
                "error": f"already installed: {target} (use --force to replace)",
                "target": str(target),
            },
            EXIT_ERROR,
        )
    shutil.copyfile(source, target)
    return emit(
        {"installed": str(target), "source": str(source)}, EXIT_RESOLVED
    )


def resolve(args: argparse.Namespace, environ: dict[str, str]) -> int:
    chain: list[str] = []

    env_session = environ.get("OPENCODE_SESSION_ID", "").strip()
    if env_session:
        chain.append("plugin_env")
        return emit(
            {
                "session_id": env_session,
                "resolution": "plugin_env",
                "chain": chain,
            },
            EXIT_RESOLVED,
        )

    pid = environ.get("OPENCODE_PID", "").strip()
    if pid:
        argv = ps_command_line(pid)
        if argv:
            flag_session = parse_launch_session(argv)
            if flag_session:
                chain.append("launch_flag")
                return emit(
                    {
                        "session_id": flag_session,
                        "resolution": "launch_flag",
                        "chain": chain,
                        "evidence": {"pid": pid},
                    },
                    EXIT_RESOLVED,
                )

    cwd = os.path.normpath(os.path.expanduser(args.cwd))
    db_path = discover_db_path(args.db_path)
    if db_path is None:
        chain.append("liveness_probe:unavailable")
        return emit(
            {
                "unresolved": "opencode db not found",
                "chain": chain,
                "candidates": [],
                "ask_user": True,
            },
            EXIT_UNRESOLVED,
        )

    now_ms = int(time.time() * 1000)
    winner, evidence = probe(
        db_path, cwd, now_ms, args.max_age_seconds, args.margin_seconds
    )
    chain.append("liveness_probe")
    if winner:
        evidence["chain"] = chain
        return emit(
            {
                "session_id": winner,
                "resolution": "liveness_probe",
                "chain": chain,
                "evidence": evidence,
            },
            EXIT_RESOLVED,
        )
    return emit(
        {
            "unresolved": "no deterministic signal matched",
            "chain": chain,
            "evidence": evidence,
            "candidates": candidates(db_path, cwd, CANDIDATE_LIMIT),
            "ask_user": True,
        },
        EXIT_UNRESOLVED,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runtime", default="opencode")
    parser.add_argument(
        "--cwd", default=os.getcwd(), help="directory filter (default: $PWD)"
    )
    parser.add_argument("--db-path", default=None)
    parser.add_argument(
        "--max-age-seconds",
        type=int,
        default=DEFAULT_MAX_AGE_SECONDS,
        help="probe freshness window (default: 900)",
    )
    parser.add_argument(
        "--margin-seconds",
        type=int,
        default=DEFAULT_MARGIN_SECONDS,
        help="required lead over the runner-up (default: 5)",
    )
    parser.add_argument(
        "--install-plugin",
        action="store_true",
        help="install brain-session-env.js into the opencode config dir",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if args.runtime not in SUPPORTED_RUNTIMES:
        return emit(
            {
                "error": f"unsupported runtime: {args.runtime} "
                f"(supported: {', '.join(SUPPORTED_RUNTIMES)})"
            },
            EXIT_UNSUPPORTED,
        )
    if args.install_plugin:
        return install_plugin(Path(__file__).resolve(), args.force)
    return resolve(args, dict(os.environ))


if __name__ == "__main__":
    sys.exit(main())

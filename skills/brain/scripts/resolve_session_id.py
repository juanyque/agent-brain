#!/usr/bin/env python3
"""Resolve the current OpenCode or Codex session id deterministically.

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

Codex uses the local App Server daemon: enumerate loaded threads, filter by
cwd, and read ``thread.sessionId`` from the sole matching thread. If the daemon
is unavailable or more than one thread matches, fail closed.

Exit codes: 0 resolved · 3 unresolved (candidates emitted) · 2 error ·
4 unsupported runtime. Stdout is always a single JSON object.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import struct
import subprocess
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

SUPPORTED_RUNTIMES = ("opencode", "codex")


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


def codex_socket_path(codex_bin: str | None = None) -> Path | None:
    """Ask the installed Codex daemon for its control socket path."""
    executable = codex_bin or shutil.which("codex")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "app-server", "daemon", "version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return None
        payload = json.loads(result.stdout)
        path = payload.get("socketPath")
        return Path(path).expanduser() if isinstance(path, str) and path else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def _ws_send(sock: socket.socket, payload: dict) -> None:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    mask = secrets.token_bytes(4)
    size = len(data)
    frame = bytearray((0x81,))
    if size < 126:
        frame.append(0x80 | size)
    elif size < 65536:
        frame.append(0x80 | 126)
        frame.extend(struct.pack("!H", size))
    else:
        frame.append(0x80 | 127)
        frame.extend(struct.pack("!Q", size))
    frame.extend(mask)
    frame.extend(byte ^ mask[index % 4] for index, byte in enumerate(data))
    sock.sendall(frame)


def _ws_read_exact(sock: socket.socket, count: int) -> bytes:
    result = bytearray()
    while len(result) < count:
        chunk = sock.recv(count - len(result))
        if not chunk:
            raise OSError("Codex App Server closed the connection")
        result.extend(chunk)
    return bytes(result)


def _ws_receive(sock: socket.socket) -> dict:
    """Read one JSON text message from the local Codex WebSocket."""
    while True:
        first, second = _ws_read_exact(sock, 2)
        opcode = first & 0x0F
        size = second & 0x7F
        if size == 126:
            size = struct.unpack("!H", _ws_read_exact(sock, 2))[0]
        elif size == 127:
            size = struct.unpack("!Q", _ws_read_exact(sock, 8))[0]
        mask = _ws_read_exact(sock, 4) if second & 0x80 else b""
        data = _ws_read_exact(sock, size)
        if mask:
            data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        if opcode == 0x8:
            raise OSError("Codex App Server sent a close frame")
        if opcode == 0x9:
            raise OSError("unexpected ping from Codex App Server")
        if opcode != 0x1:
            continue
        message = json.loads(data.decode("utf-8"))
        if isinstance(message, dict):
            return message


def app_server_request(
    socket_path: Path, method: str, params: dict, request_id: int
) -> dict:
    """Make one bounded JSON-RPC request through Codex's Unix WebSocket."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect(str(socket_path))
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        handshake = (
            "GET / HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        sock.sendall(handshake)
        response = bytearray()
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                raise OSError("Codex App Server closed during WebSocket handshake")
            response.extend(chunk)
            if len(response) > 16384:
                raise OSError("oversized Codex App Server handshake")
        headers, _ = bytes(response).split(b"\r\n\r\n", 1)
        if not headers.startswith(b"HTTP/1.1 101"):
            raise OSError("Codex App Server rejected the WebSocket handshake")
        expected_accept = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()
        )
        accept_header = b"sec-websocket-accept: " + expected_accept.lower()
        if accept_header not in headers.lower():
            raise OSError("invalid Codex App Server WebSocket handshake")

        _ws_send(
            sock,
            {
                "method": "initialize",
                "id": 0,
                "params": {
                    "clientInfo": {
                        "name": "agent-brain-session-resolver",
                        "title": "Resolve current Codex session",
                        "version": "1.0.0",
                    }
                },
            },
        )
        while True:
            message = _ws_receive(sock)
            if message.get("id") == 0:
                if message.get("error"):
                    raise OSError("Codex App Server initialize failed")
                break
        _ws_send(sock, {"method": "initialized", "params": {}})
        _ws_send(sock, {"method": method, "id": request_id, "params": params})
        while True:
            message = _ws_receive(sock)
            if message.get("id") == request_id:
                return message


def _same_directory(candidate: str, cwd: str) -> bool:
    return os.path.normcase(os.path.realpath(candidate)) == os.path.normcase(
        os.path.realpath(cwd)
    )


def resolve_codex_session(
    cwd: str, socket_path: Path | None = None
) -> tuple[str | None, dict]:
    """Resolve only when one loaded Codex thread matches the current cwd."""
    evidence: dict = {"cwd": cwd}
    socket_path = socket_path or codex_socket_path()
    if socket_path is None:
        evidence["app_server_error"] = "local Codex App Server socket unavailable"
        return None, evidence
    evidence["app_server_socket"] = str(socket_path)
    try:
        data: list[str] = []
        cursor = None
        request_id = 1
        seen_cursors: set[str] = set()
        while True:
            params = {"cursor": cursor} if cursor else {}
            loaded = app_server_request(
                socket_path, "thread/loaded/list", params, request_id
            )
            request_id += 1
            if "error" in loaded:
                raise OSError("thread/loaded/list request failed")
            page = loaded.get("result", {})
            data.extend(page.get("data", []))
            cursor = page.get("nextCursor")
            if not cursor:
                break
            if cursor in seen_cursors:
                raise OSError("Codex App Server repeated a loaded-thread cursor")
            seen_cursors.add(cursor)
        matching = []
        for thread_id in data:
            response = app_server_request(
                socket_path, "thread/read", {"threadId": thread_id}, request_id
            )
            request_id += 1
            if "error" in response:
                raise OSError("thread/read request failed")
            thread = response.get("result", {}).get("thread", {})
            thread_cwds = [thread.get("cwd", "")]
            thread_cwds.extend(
                env.get("cwd", "") for env in thread.get("environments", [])
            )
            if any(path and _same_directory(path, cwd) for path in thread_cwds):
                matching.append(
                    {
                        "thread_id": thread_id,
                        "session_id": thread.get("sessionId"),
                    }
                )
        evidence["loaded_threads_in_cwd"] = len(matching)
        if len(matching) != 1 or not matching[0].get("session_id"):
            evidence["matching_threads"] = matching
            evidence["probe_error"] = "no unique loaded Codex thread for cwd"
            return None, evidence
        evidence["thread_id"] = matching[0]["thread_id"]
        return matching[0]["session_id"], evidence
    except (
        OSError,
        socket.timeout,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        AttributeError,
    ) as error:
        evidence["app_server_error"] = str(error)
        return None, evidence


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

    if args.runtime == "codex":
        env_session = environ.get("CODEX_SESSION_ID", "").strip()
        if env_session:
            chain.append("codex_session_id_env")
            return emit(
                {
                    "session_id": env_session,
                    "resolution": "codex_session_id_env",
                    "chain": chain,
                    "evidence": {"environment": "CODEX_SESSION_ID"},
                },
                EXIT_RESOLVED,
            )

        # CODEX_THREAD_ID can identify a forked thread, not the session id
        # required by `codex resume`; use App Server as the fallback.
        cwd = os.path.normpath(os.path.expanduser(args.cwd))
        configured_socket = (
            Path(args.socket_path).expanduser() if args.socket_path else None
        )
        session_id, evidence = resolve_codex_session(cwd, configured_socket)
        chain.append("app_server_loaded_thread")
        if session_id:
            evidence["chain"] = chain
            return emit(
                {
                    "session_id": session_id,
                    "resolution": "app_server_loaded_thread",
                    "chain": chain,
                    "evidence": evidence,
                },
                EXIT_RESOLVED,
            )
        return emit(
            {
                "unresolved": "no deterministic Codex session signal matched",
                "chain": chain,
                "evidence": evidence,
                "candidates": evidence.get("matching_threads", []),
                "ask_user": True,
            },
            EXIT_UNRESOLVED,
        )

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
        "--socket-path",
        default=None,
        help="Codex App Server Unix socket override (runtime codex only)",
    )
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
    if args.install_plugin and args.runtime != "opencode":
        return emit(
            {"error": "--install-plugin is only supported for runtime opencode"},
            EXIT_ERROR,
        )
    if args.install_plugin:
        return install_plugin(Path(__file__).resolve(), args.force)
    return resolve(args, dict(os.environ))


if __name__ == "__main__":
    sys.exit(main())

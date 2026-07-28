from __future__ import annotations

import os
import shlex
import subprocess
import stat
from datetime import UTC, datetime
from pathlib import Path

from evidence_closure_records import pin_json
from evidence_json import (
    ContractError,
    JsonValue,
    create_bytes,
    create_json,
    digest,
    file_record,
    load_json,
    read_bytes_no_follow,
)
from evidence_invocations import TodoProof, expected_todo_proof, scan_invocation_dollars
from evidence_git import controlled_environment
from evidence_implementation import implementation_git_state_sha, implementation_sha


def _controlled_shell_environment(todo_proof: TodoProof | None, pycache_root: Path) -> dict[str, str]:
    result = controlled_environment({"PYTHONPYCACHEPREFIX": str(pycache_root)})
    if todo_proof is not None:
        result.update(dict(todo_proof.environment_bindings))
    return result


def _timeout_seconds() -> float:
    raw = os.environ.get("AGENT_BRAIN_COMMAND_TIMEOUT_SECONDS", "3600")
    try:
        value = float(raw)
    except ValueError as error:
        raise ContractError("invalid command timeout") from error
    if value <= 0:
        raise ContractError("command timeout must be positive")
    return value


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _implementation_sha(root: Path) -> str:
    return implementation_sha(root)


def _implementation_git_sha(root: Path) -> str:
    return implementation_git_state_sha(root)


def _plan_sha(root: Path) -> str:
    active_plan = root / ".omo" / "plans" / "agent-brain-operating-model.md"
    if active_plan.is_file():
        return digest(read_bytes_no_follow(active_plan))
    model = load_json(root / "model/OPERATING-MODEL.json")
    return str(model["baseline"]["plan_sha256"])


def run_command(
    *,
    scope: str,
    identity: str,
    step: int,
    cwd: Path,
    evidence_root: Path,
    command: list[str] | None,
    shell: str | None,
    plan_sha: str,
    freeze_sha: str | None = None,
    todo_proof: TodoProof | None = None,
    reserve_step: bool = False,
) -> int:
    run_dir = evidence_root / f"{identity}-runs"
    try:
        run_dir.mkdir(mode=0o700)
    except FileExistsError:
        pass
    try:
        info = os.lstat(run_dir)
    except OSError as error:
        raise ContractError("run directory is unsafe") from error
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ContractError("run directory is unsafe")
    output = run_dir / f"{step}.stdout"
    errors = run_dir / f"{step}.stderr"
    record = run_dir / f"{step}.json"
    reservation = run_dir / f"{step}.owner"
    guarded = (output, errors, record, reservation) if reserve_step else (output, errors, record)
    if any(path.exists() or path.is_symlink() for path in guarded):
        raise ContractError("run outputs are create-only")
    if (command is None) == (shell is None):
        raise ContractError("provide exactly one argv or shell command")
    started = _now()
    pycache_root = evidence_root / f"{identity}-pycache"
    environment_contract = controlled_environment({"PYTHONPYCACHEPREFIX": str(pycache_root)})
    if reserve_step:
        create_json(
            reservation,
            {
                "created_at": started,
                "identity": identity,
                "schema_version": "agent-brain-run-owner/v1",
                "step": step,
            },
        )
    try:
        if shell is None:
            assert command is not None
            result = subprocess.run(
                command, cwd=cwd, capture_output=True, check=False,
                env=_controlled_shell_environment(todo_proof, pycache_root),
                timeout=_timeout_seconds(),
            )
            invocation: JsonValue = command
            mode = "argv"
        else:
            result = subprocess.run(
                shell,
                cwd=cwd,
                env=_controlled_shell_environment(todo_proof, pycache_root),
                shell=True,
                executable="/bin/sh",
                capture_output=True,
                check=False,
                timeout=_timeout_seconds(),
            )
            invocation = shell
            mode = "shell"
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, bytes) else b""
        stderr = error.stderr if isinstance(error.stderr, bytes) else b""
        stderr += b"command timed out\n"
        result = subprocess.CompletedProcess(error.cmd, 124, stdout, stderr)
        invocation = shell if shell is not None else command or []
        mode = "shell" if shell is not None else "argv"
    create_bytes(output, result.stdout)
    create_bytes(errors, result.stderr)
    product_sha = _implementation_sha(cwd)
    git_sha = _implementation_git_sha(cwd)
    value: dict[str, JsonValue] = {
        "command": invocation,
        "completed_at": _now(),
        "cwd": str(cwd.resolve()),
        "environment_contract": environment_contract,
        "environment_contract_sha256": digest(
            "\n".join(f"{key}={environment_contract[key]}" for key in sorted(environment_contract)).encode("utf-8")
        ),
        "exit_status": result.returncode,
        "identity": identity,
        "implementation_product_sha256": product_sha,
        "implementation_git_state_sha256": git_sha,
        "implementation_sha256": product_sha,
        "mode": mode,
        "plan_sha256": plan_sha,
        "schema_version": "agent-brain-run/v1",
        "scope": scope,
        "started_at": started,
        "stderr": file_record("evidence", evidence_root, errors),
        "stderr_sha256": digest(result.stderr),
        "stdout": file_record("evidence", evidence_root, output),
        "stdout_sha256": digest(result.stdout),
        "step": step,
        "status_sha256": digest(f"{result.returncode}\n".encode("ascii")),
    }
    if freeze_sha is not None:
        value["freeze_sha256"] = freeze_sha
    if todo_proof is not None:
        value.update(todo_proof.record_fields())
    create_json(record, value)
    return result.returncode


def run_todo(
    todo: int,
    step: int,
    cwd: Path,
    evidence_root: Path,
    command: list[str] | None,
    shell: str | None,
) -> int:
    proof = expected_todo_proof(todo, step, cwd, evidence_root)
    if shell is not None:
        scan_invocation_dollars(None, shell)
    actual_mode = "shell" if shell is not None else "argv"
    actual_command = shell if shell is not None else shlex.join(command or [])
    if proof.mode != actual_mode or proof.canonical_command != actual_command:
        raise ContractError("invocation differs from canonical QA command")
    for prior in range(1, step):
        if not (evidence_root / f"task-{todo}-runs/{prior}.json").is_file():
            raise ContractError("todo steps must run in order")
    return run_command(
        scope="todo",
        identity=f"task-{todo}",
        step=step,
        cwd=cwd,
        evidence_root=evidence_root,
        command=command,
        shell=shell,
        plan_sha=_plan_sha(cwd),
        todo_proof=proof,
    )


def run_lane(
    lane: str,
    step: int,
    cwd: Path,
    freeze: Path,
    evidence_root: Path,
    command: list[str] | None,
    shell: str | None,
) -> int:
    pinned_freeze = pin_json(freeze)
    freeze_data = pinned_freeze.data
    frozen = pinned_freeze.value
    expected_product = frozen.get("implementation_sha256")
    if not isinstance(expected_product, str):
        raise ContractError("freeze implementation hash is missing")
    if implementation_sha(cwd) != expected_product:
        raise ContractError("lane cwd product differs from freeze")
    expected_git = frozen.get("implementation_git_state_sha256")
    if isinstance(expected_git, str) and implementation_git_state_sha(cwd) != expected_git:
        raise ContractError("lane cwd Git state differs from freeze")
    status = run_command(
        scope="lane",
        identity=lane,
        step=step,
        cwd=cwd,
        evidence_root=evidence_root,
        command=command,
        shell=shell,
        plan_sha=str(frozen["plan_sha256"]),
        freeze_sha=digest(freeze_data),
        reserve_step=True,
    )
    if status == 0:
        if implementation_sha(cwd) != expected_product:
            return 2
        if isinstance(expected_git, str) and implementation_git_state_sha(cwd) != expected_git:
            return 2
    return status

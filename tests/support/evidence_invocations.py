from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from evidence_json import ContractError, JsonValue, canonical_bytes, digest, load_json
from evidence_placeholder_bindings import (
    BindingRecord,
    bindings_from_values,
    bindings_for_placeholders,
    expand_manifest_text,
    scan_dollars,
    scan_shell_dollars,
)

TODO_WRAPPER: Final = "agent-brain-run-todo/v1"


@dataclass(frozen=True, slots=True)
class TodoProof:
    todo: int
    ordinal: int
    mode: str
    manifest_command: str
    canonical_command: str
    canonical_argv: tuple[str, ...] | None
    environment_bindings: tuple[tuple[str, str], ...]
    environment_binding_records: tuple[BindingRecord, ...]
    alias: str | None

    def record_fields(self) -> dict[str, JsonValue]:
        bindings: dict[str, JsonValue] = dict(self.environment_bindings)
        binding_records: list[JsonValue] = [
            {"name": name, "path": path, "role": role, "root": root, "sha256": path_hash}
            for name, path, path_hash, root, role in self.environment_binding_records
        ]
        fields: dict[str, JsonValue] = {
            "canonical_command": self.canonical_command,
            "environment_binding_sha256": digest(canonical_bytes(bindings)),
            "environment_binding_records": binding_records,
            "environment_bindings": bindings,
            "manifest_command": self.manifest_command,
            "ordinal": self.ordinal,
            "run_todo_wrapper": TODO_WRAPPER,
            "todo": self.todo,
        }
        if self.canonical_argv is not None:
            fields["canonical_argv"] = list(self.canonical_argv)
        if self.alias is not None:
            fields["alias"] = self.alias
        return fields


def _expected_step(root: Path, todo: int, step: int) -> dict[str, JsonValue]:
    manifest = load_json(root / "tests/fixtures/operating-model-qa-commands.json")
    todos = manifest.get("todos")
    if not isinstance(todos, list):
        raise ContractError("invalid QA command manifest")
    match = next(
        (item for item in todos if isinstance(item, dict) and item.get("todo") == todo),
        None,
    )
    if not isinstance(match, dict):
        raise ContractError(f"unknown todo: {todo}")
    steps = match.get("steps")
    if not isinstance(steps, list) or step < 1 or step > len(steps):
        raise ContractError(f"unknown todo step: {todo}/{step}")
    value = steps[step - 1]
    if not isinstance(value, dict) or value.get("step") != step:
        raise ContractError("QA steps are not contiguous")
    return value


def scan_invocation_dollars(command: list[str] | None, shell: str | None) -> None:
    if shell is not None:
        scan_shell_dollars(shell)
    for argument in command or []:
        scan_dollars(argument)


def _split_manifest_argv(command: str) -> tuple[str, ...]:
    try:
        return tuple(shlex.split(command))
    except ValueError as error:
        raise ContractError("manifest command cannot be parsed") from error


def _todo_proof(
    todo: int,
    step: int,
    command: str,
    mode: str,
    alias: str | None,
    bindings: tuple[tuple[str, str], ...],
    binding_records: tuple[BindingRecord, ...],
) -> TodoProof:
    if mode == "argv":
        argv = tuple(expand_manifest_text(token, bindings) for token in _split_manifest_argv(command))
        return TodoProof(todo, step, mode, command, shlex.join(argv), argv, bindings, binding_records, alias)
    return TodoProof(
        todo,
        step,
        mode,
        command,
        command,
        None,
        bindings,
        binding_records,
        alias,
    )


def _reviewed_plan_command(todo: int, step: int, command: str, mode: str) -> bool:
    return (
        todo == 1
        and step == 2
        and mode == "argv"
        and command == (
            'python3 tests/support/evidence_contract.py plan-review --plan "$PLAN" '
            '--draft "$DRAFT" --momus-receipt "$PLAN_REVIEW_ROOT/momus.txt" '
            '--independent-receipt "$PLAN_REVIEW_ROOT/independent.txt" --output "$REVIEW_SEAL"'
        )
    )


def _expected_command(root: Path, todo: int, step: int) -> tuple[str, str, str | None, frozenset[str], bool]:
    expected = _expected_step(root, todo, step)
    command = expected.get("command")
    mode = expected.get("mode")
    alias = expected.get("alias")
    if not isinstance(command, str) or mode not in {"argv", "shell"}:
        raise ContractError("invalid QA command")
    if alias is not None and not isinstance(alias, str):
        raise ContractError("invalid QA command alias")
    placeholders = scan_shell_dollars(command) if mode == "shell" else scan_dollars(command)
    return command, mode, alias, placeholders, _reviewed_plan_command(todo, step, command, mode)


def expected_todo_proof(todo: int, step: int, cwd: Path, evidence_root: Path) -> TodoProof:
    command, mode, alias, placeholders, reviewed_plan = _expected_command(cwd, todo, step)
    bindings, binding_records = bindings_for_placeholders(
        evidence_root,
        cwd,
        placeholders,
        os.environ,
        reviewed_plan=reviewed_plan,
    )
    return _todo_proof(todo, step, command, mode, alias, bindings, binding_records)


def expected_todo_proof_from_bindings(
    todo: int,
    step: int,
    cwd: Path,
    evidence_root: Path,
    binding_values: Mapping[str, str],
) -> TodoProof:
    command, mode, alias, placeholders, reviewed_plan = _expected_command(cwd, todo, step)
    bindings, binding_records = bindings_from_values(
        evidence_root,
        cwd,
        placeholders,
        binding_values,
        reviewed_plan=reviewed_plan,
    )
    return _todo_proof(todo, step, command, mode, alias, bindings, binding_records)

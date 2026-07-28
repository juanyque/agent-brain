from __future__ import annotations

import os
import stat
import string
from collections.abc import Mapping
from pathlib import Path
from typing import Final, TypeAlias

from evidence_json import ContractError, digest

PLACEHOLDERS: Final = (
    "EVIDENCE_ROOT",
    "PLAN",
    "DRAFT",
    "PLAN_REVIEW_ROOT",
    "REVIEW_SEAL",
    "SOURCE_ROOT",
    "BRAIN_ROOT",
    "IMPL_ROOT",
)
PLACEHOLDER_SET: Final = frozenset(PLACEHOLDERS)
NAME_CHARACTERS: Final = frozenset(string.ascii_letters + string.digits + "_")
BindingRecord: TypeAlias = tuple[str, str, str, str, str]


def _absolute_path(name: str, raw: str) -> Path:
    if raw == "":
        raise ContractError(f"missing placeholder binding: {name}")
    if "\x00" in raw:
        raise ContractError(f"unsafe placeholder binding: {name}")
    path = Path(raw)
    if not path.is_absolute():
        raise ContractError(f"placeholder binding must be absolute: {name}")
    if ".." in path.parts:
        raise ContractError(f"placeholder binding escapes root: {name}")
    return path


def _reject_symlink_entry(name: str, path: Path) -> None:
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError as error:
        raise ContractError(f"placeholder binding path is missing: {name}") from error
    if stat.S_ISLNK(mode):
        raise ContractError(f"placeholder binding uses symlink: {name}")


def _reject_symlink_components(name: str, path: Path, *, allow_missing_final: bool) -> None:
    current = Path(path.anchor)
    for index, part in enumerate(path.parts[1:]):
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError as error:
            if allow_missing_final and index == len(path.parts) - 2:
                return
            raise ContractError(f"placeholder binding path is missing: {name}") from error
        if stat.S_ISLNK(mode):
            raise ContractError(f"placeholder binding uses symlink: {name}")


def _reject_relative_symlinks(
    name: str,
    root: Path,
    path: Path,
    *,
    allow_missing_final: bool,
) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise ContractError(f"placeholder binding outside root: {name}") from error
    current = root
    parts = relative.parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError as error:
            if allow_missing_final and index == len(parts) - 1:
                return
            raise ContractError(f"placeholder binding path is missing: {name}") from error
        if stat.S_ISLNK(mode):
            raise ContractError(f"placeholder binding uses symlink: {name}")


def _existing_file(name: str, raw: str) -> Path:
    path = _absolute_path(name, raw)
    _reject_symlink_components(name, path, allow_missing_final=False)
    if not path.is_file():
        raise ContractError(f"placeholder binding must be a file: {name}")
    return path.resolve(strict=True)


def _existing_dir(name: str, raw: str) -> Path:
    path = _absolute_path(name, raw)
    _reject_symlink_components(name, path, allow_missing_final=False)
    if not path.is_dir():
        raise ContractError(f"placeholder binding must be a directory: {name}")
    return path.resolve(strict=True)


def _output_path(name: str, raw: str) -> Path:
    path = _absolute_path(name, raw)
    _reject_symlink_components(name, path, allow_missing_final=True)
    _existing_dir(f"{name} parent", str(path.parent))
    return path.resolve(strict=False)


def _require_under(name: str, path: Path, root_name: str, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ContractError(f"placeholder binding outside {root_name}: {name}") from error


def _environment_path(name: str, environ: Mapping[str, str]) -> Path:
    value = environ.get(name)
    if value is None:
        raise ContractError(f"missing placeholder binding: {name}")
    return _absolute_path(name, value)


def _check_environment_match(name: str, expected: Path, environ: Mapping[str, str]) -> None:
    value = environ.get(name)
    if value is None:
        return
    supplied = _existing_dir(name, value)
    if supplied != expected:
        raise ContractError(f"placeholder binding mismatch: {name}")


def _required_binding_names(placeholders: frozenset[str], *, reviewed_plan: bool) -> frozenset[str]:
    required = set(placeholders)
    if placeholders & {"PLAN", "PLAN_REVIEW_ROOT", "REVIEW_SEAL"}:
        required.add("EVIDENCE_ROOT")
    if placeholders & {"PLAN", "IMPL_ROOT"}:
        required.add("IMPL_ROOT")
    if "DRAFT" in placeholders or ("PLAN" in placeholders and reviewed_plan):
        required.add("BRAIN_ROOT")
    return frozenset(required)


def binding_records(
    bindings: tuple[tuple[str, str], ...],
    roots: Mapping[str, str],
    roles: Mapping[str, str],
) -> tuple[BindingRecord, ...]:
    return tuple(
        (name, value, digest(value.encode("utf-8")), roots[name], roles[name])
        for name, value in bindings
    )


def bindings_from_values(
    evidence_root: Path,
    cwd: Path,
    placeholders: frozenset[str],
    supplied: Mapping[str, str],
    *,
    reviewed_plan: bool = False,
) -> tuple[tuple[tuple[str, str], ...], tuple[BindingRecord, ...]]:
    required = _required_binding_names(placeholders, reviewed_plan=reviewed_plan)
    if not required:
        return (), ()
    evidence: Path | None = None
    if "EVIDENCE_ROOT" in required:
        evidence = _existing_dir("EVIDENCE_ROOT", supplied.get("EVIDENCE_ROOT", ""))
        expected_evidence = _existing_dir("EVIDENCE_ROOT", str(evidence_root))
        if evidence != expected_evidence:
            raise ContractError("placeholder binding mismatch: EVIDENCE_ROOT")
    impl: Path | None = None
    if "IMPL_ROOT" in required:
        impl = _existing_dir("IMPL_ROOT", supplied.get("IMPL_ROOT", ""))
        expected_impl = _existing_dir("IMPL_ROOT", str(cwd))
        if impl != expected_impl:
            raise ContractError("placeholder binding mismatch: IMPL_ROOT")
    values: dict[str, str] = {}
    roots: dict[str, str] = {}
    roles: dict[str, str] = {}
    def add(name: str, path: Path, root: str, role: str) -> None:
        values[name] = str(path)
        roots[name] = root
        roles[name] = role
    if "EVIDENCE_ROOT" in required:
        add("EVIDENCE_ROOT", evidence, "evidence", "evidence-root")
    if "IMPL_ROOT" in required:
        add("IMPL_ROOT", impl, "implementation", "implementation-root")
    brain: Path | None = None
    if "BRAIN_ROOT" in required:
        brain = _existing_dir("BRAIN_ROOT", str(_environment_path("BRAIN_ROOT", supplied)))
        add("BRAIN_ROOT", brain, "brain", "brain-root")
    if "SOURCE_ROOT" in required:
        source = _existing_dir("SOURCE_ROOT", str(_environment_path("SOURCE_ROOT", supplied)))
        add("SOURCE_ROOT", source, "source", "source-root")
    if "PLAN" in required:
        plan = _existing_file("PLAN", str(_environment_path("PLAN", supplied)))
        if reviewed_plan:
            if brain is None:
                raise ContractError("missing placeholder binding: BRAIN_ROOT")
            _require_under("PLAN", plan, "BRAIN_ROOT", brain / ".omo" / "plans")
            _reject_relative_symlinks("PLAN", brain, plan, allow_missing_final=False)
            add("PLAN", plan, "brain", "reviewed-plan")
        else:
            if impl is None:
                impl = _existing_dir("IMPL_ROOT", str(cwd))
            active_plan = impl / ".omo" / "plans" / "agent-brain-operating-model.md"
            if plan != _existing_file("PLAN", str(active_plan)):
                raise ContractError("placeholder binding is not the selected active plan: PLAN")
            _reject_relative_symlinks("PLAN", impl, plan, allow_missing_final=False)
            add("PLAN", plan, "implementation", "active-plan")
    if "DRAFT" in required:
        if brain is None:
            raise ContractError("missing placeholder binding: BRAIN_ROOT")
        draft = _existing_file("DRAFT", str(_environment_path("DRAFT", supplied)))
        _require_under("DRAFT", draft, "BRAIN_ROOT", brain / ".omo" / "drafts")
        _reject_relative_symlinks("DRAFT", brain, draft, allow_missing_final=False)
        add("DRAFT", draft, "brain", "review-draft")
    review_root: Path | None = None
    if "PLAN_REVIEW_ROOT" in required:
        if evidence is None:
            evidence = _existing_dir("EVIDENCE_ROOT", str(evidence_root))
        review_root = _existing_dir("PLAN_REVIEW_ROOT", str(_environment_path("PLAN_REVIEW_ROOT", supplied)))
        _require_under("PLAN_REVIEW_ROOT", review_root, "EVIDENCE_ROOT", evidence)
        _reject_relative_symlinks("PLAN_REVIEW_ROOT", evidence, review_root, allow_missing_final=False)
        add("PLAN_REVIEW_ROOT", review_root, "evidence", "plan-review-root")
    if "REVIEW_SEAL" in required:
        if review_root is None:
            raise ContractError("missing placeholder binding: PLAN_REVIEW_ROOT")
        review_seal = _output_path("REVIEW_SEAL", str(_environment_path("REVIEW_SEAL", supplied)))
        _require_under("REVIEW_SEAL", review_seal, "PLAN_REVIEW_ROOT", review_root)
        _reject_relative_symlinks("REVIEW_SEAL", review_root, review_seal, allow_missing_final=True)
        add("REVIEW_SEAL", review_seal, "evidence", "plan-review-seal")
    bindings = tuple((name, values[name]) for name in PLACEHOLDERS if name in values)
    return bindings, binding_records(bindings, roots, roles)


def bindings_for_placeholders(
    evidence_root: Path,
    cwd: Path,
    placeholders: frozenset[str],
    environ: Mapping[str, str],
    *,
    reviewed_plan: bool = False,
) -> tuple[tuple[tuple[str, str], ...], tuple[BindingRecord, ...]]:
    supplied = dict(environ)
    supplied.setdefault("EVIDENCE_ROOT", str(evidence_root))
    supplied.setdefault("IMPL_ROOT", str(cwd))
    return bindings_from_values(evidence_root, cwd, placeholders, supplied, reviewed_plan=reviewed_plan)


def scan_dollars(value: str) -> frozenset[str]:
    if "`" in value or "<(" in value or ">(" in value:
        raise ContractError("command substitution is not allowed")
    placeholders: set[str] = set()
    index = 0
    while index < len(value):
        character = value[index]
        if character != "$":
            index += 1
            continue
        if index > 0 and value[index - 1] == "\\":
            raise ContractError("undeclared placeholder")
        if value.startswith("${", index):
            end = value.find("}", index + 2)
            if end == -1:
                raise ContractError("undeclared placeholder")
            name = value[index + 2:end]
            if name not in PLACEHOLDER_SET:
                raise ContractError("undeclared placeholder")
            placeholders.add(name)
            index = end + 1
            continue
        name_start = index + 1
        if name_start >= len(value) or value[name_start] not in string.ascii_letters + "_":
            raise ContractError("undeclared placeholder")
        name_end = name_start
        while name_end < len(value) and value[name_end] in NAME_CHARACTERS:
            name_end += 1
        name = value[name_start:name_end]
        if name not in PLACEHOLDER_SET:
            raise ContractError("undeclared placeholder")
        placeholders.add(name)
        index = name_end
    return frozenset(placeholders)


def _local_assignment_name(value: str, dollar_index: int) -> str | None:
    if dollar_index < 2 or value[dollar_index - 1] != "=":
        return None
    name_end = dollar_index - 1
    name_start = name_end
    while name_start > 0 and value[name_start - 1] in NAME_CHARACTERS:
        name_start -= 1
    name = value[name_start:name_end]
    if name != "status":
        return None
    prefix = value[:name_start].rstrip()
    if not prefix or prefix[-1] not in ";\n":
        return None
    return name


def scan_shell_dollars(value: str) -> frozenset[str]:
    if "`" in value or "<(" in value or ">(" in value:
        raise ContractError("command substitution is not allowed")
    placeholders: set[str] = set()
    local_names: set[str] = set()
    index = 0
    while index < len(value):
        character = value[index]
        if character != "$":
            index += 1
            continue
        if index > 0 and value[index - 1] == "\\":
            raise ContractError("undeclared placeholder")
        if value.startswith("${", index):
            end = value.find("}", index + 2)
            if end == -1:
                raise ContractError("undeclared placeholder")
            name = value[index + 2:end]
            if name not in PLACEHOLDER_SET:
                raise ContractError("undeclared placeholder")
            placeholders.add(name)
            index = end + 1
            continue
        if value.startswith("$?", index):
            name = _local_assignment_name(value, index)
            if name is None:
                raise ContractError("undeclared placeholder")
            local_names.add(name)
            index += 2
            continue
        name_start = index + 1
        if name_start >= len(value) or value[name_start] not in string.ascii_letters + "_":
            raise ContractError("undeclared placeholder")
        name_end = name_start
        while name_end < len(value) and value[name_end] in NAME_CHARACTERS:
            name_end += 1
        name = value[name_start:name_end]
        if name in PLACEHOLDER_SET:
            placeholders.add(name)
        elif name not in local_names:
            raise ContractError("undeclared placeholder")
        index = name_end
    return frozenset(placeholders)


def expand_manifest_text(value: str, bindings: tuple[tuple[str, str], ...]) -> str:
    bound = dict(bindings)
    result: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character != "$":
            result.append(character)
            index += 1
            continue
        if value.startswith("${", index):
            end = value.find("}", index + 2)
            name = value[index + 2:end]
            if name not in bound:
                raise ContractError("undeclared placeholder")
            result.append(bound[name])
            index = end + 1
            continue
        name_start = index + 1
        name_end = name_start
        while name_end < len(value) and value[name_end] in NAME_CHARACTERS:
            name_end += 1
        name = value[name_start:name_end]
        if name not in bound:
            raise ContractError("undeclared placeholder")
        result.append(bound[name])
        index = name_end
    return "".join(result)

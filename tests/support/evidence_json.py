from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias


SCHEMA: Final = "agent-brain-evidence/v1"
ROOTS: Final = frozenset({"source", "brain", "implementation", "evidence", "qa"})
JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
BytesOutput: TypeAlias = tuple[Path, bytes]
_DIRECTORY_FLAGS: Final = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
_CREATE_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
_FSTAT_ATTEMPTS: Final = 3
_QUARANTINE_PREFIX: Final = ".__agent-brain-quarantine-"


@dataclass(frozen=True, slots=True)
class ContractError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class _OutputSpec:
    path: Path
    parent_parts: tuple[str, ...]
    leaf: str


@dataclass(frozen=True, slots=True)
class _PinnedOutput:
    path: Path
    parent_fd: int
    leaf: str


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int


def _pairs(items: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in items:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json_bytes(data: bytes, path: Path) -> dict[str, JsonValue]:
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError(f"invalid JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ContractError("JSON root must be an object")
    return value


def load_json(path: Path) -> dict[str, JsonValue]:
    return parse_json_bytes(read_bytes_no_follow(path), path)


def canonical_bytes(value: JsonValue) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode_path(path: bytes) -> str:
    return base64.b64encode(path).decode("ascii")


def decode_path(value: JsonValue) -> bytes:
    if not isinstance(value, str):
        raise ContractError("path_b64 must be a string")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise ContractError("invalid base64 path") from error
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ContractError("path_b64 must use padded canonical base64")
    parts = decoded.split(b"/")
    if not decoded or decoded.startswith(b"/") or any(part in {b"", b".", b".."} for part in parts):
        raise ContractError("unsafe relative path")
    return decoded


def validate_root(value: JsonValue) -> str:
    if not isinstance(value, str) or value not in ROOTS:
        raise ContractError("unknown root")
    return value


def validate_manifest(value: dict[str, JsonValue]) -> None:
    root = value.get("root")
    if root is not None:
        validate_root(root)
    entries = value.get("entries", [])
    if not isinstance(entries, list):
        raise ContractError("entries must be an array")
    seen: set[bytes] = set()
    previous: bytes | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            raise ContractError("entry must be an object")
        path = decode_path(entry.get("path_b64"))
        if path in seen:
            raise ContractError("duplicate manifest path")
        if previous is not None and path <= previous:
            raise ContractError("manifest paths are out of order")
        seen.add(path)
        previous = path


def _is_macos_var_alias(path: Path) -> bool:
    if path != Path("/var"):
        return False
    try:
        return path.resolve(strict=True) == Path("/private/var")
    except OSError:
        return False


def _is_macos_tmp_alias(path: Path) -> bool:
    if sys.platform != "darwin" or path != Path("/tmp"):
        return False
    try:
        return os.readlink(path) == "private/tmp" and path.resolve(strict=True) == Path(
            "/private/tmp"
        )
    except OSError:
        return False


def _absolute_parts(path: Path) -> tuple[str, ...]:
    absolute = path if path.is_absolute() else Path.cwd() / path
    parts = absolute.parts[1:]
    if parts[:1] == ("tmp",) and _is_macos_tmp_alias(Path("/tmp")):
        return ("private", "tmp", *parts[1:])
    if parts[:1] == ("var",) and _is_macos_var_alias(Path("/var")):
        return ("private", "var", *parts[1:])
    return parts


def _parse_output_path(path: Path) -> _OutputSpec:
    parts = _absolute_parts(path)
    if not parts:
        raise ContractError(f"create-only destination rejected: {path}")
    for part in parts:
        if part in {"", ".", ".."}:
            raise ContractError(f"unsafe output path: {path}")
    return _OutputSpec(path, parts[:-1], parts[-1])


def _prepare_create_destination(path: Path) -> _PinnedOutput:
    spec = _parse_output_path(path)
    parent_fd = _pin_parent(spec)
    try:
        _require_absent_leaf(parent_fd, spec.leaf, spec.path)
        return _PinnedOutput(spec.path, parent_fd, spec.leaf)
    except (OSError, ContractError):
        os.close(parent_fd)
        raise


def _pin_parent(spec: _OutputSpec) -> int:
    root_fd = _open_root(spec.path)
    current_fd = root_fd
    try:
        for part in spec.parent_parts:
            next_fd = _open_child_directory(current_fd, part, spec.path)
            try:
                current_fd = _replace_parent_fd(current_fd, next_fd, spec.path)
            except ContractError:
                current_fd = -1
                raise
        return current_fd
    except (OSError, ContractError):
        if current_fd >= 0:
            os.close(current_fd)
        raise


def _replace_parent_fd(current_fd: int, next_fd: int, path: Path) -> int:
    try:
        os.close(current_fd)
    except OSError as error:
        try:
            os.close(next_fd)
        except OSError as cleanup_error:
            raise ContractError(f"parent descriptor cleanup failed: {path}") from cleanup_error
        raise ContractError(f"parent descriptor close failed: {path}") from error
    return next_fd


def _open_root(path: Path) -> int:
    try:
        return os.open("/", _DIRECTORY_FLAGS)
    except OSError as error:
        raise ContractError(f"parent directory does not exist: {path}") from error


def _open_child_directory(parent_fd: int, part: str, path: Path) -> int:
    try:
        return os.open(part, _DIRECTORY_FLAGS | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
    except OSError as error:
        raise ContractError(f"parent directory is not a real directory: {path}") from error


def _require_absent_leaf(parent_fd: int, leaf: str, path: Path) -> None:
    try:
        os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as error:
        raise ContractError(f"create-only destination rejected: {path}") from error
    raise ContractError(f"create-only destination rejected: {path}")


def _identity(metadata: os.stat_result) -> _FileIdentity:
    return _FileIdentity(metadata.st_dev, metadata.st_ino)


def _fstat_identity(descriptor: int, path: Path) -> _FileIdentity:
    last_error: OSError | None = None
    for _ in range(_FSTAT_ATTEMPTS):
        try:
            return _identity(os.fstat(descriptor))
        except OSError as error:
            last_error = error
    if last_error is None:
        raise ContractError(f"created output identity unavailable: {path}")
    raise ContractError(f"created output identity unavailable: {path}") from last_error


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    written = 0
    while written < len(view):
        count = os.write(descriptor, view[written:])
        if count == 0:
            raise OSError("short write")
        written += count


def read_bytes_no_follow(path: Path) -> bytes:
    spec = _parse_output_path(path)
    parent_fd = _pin_parent(spec)
    try:
        try:
            descriptor = os.open(
                spec.leaf,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
        except OSError as error:
            raise ContractError(f"file cannot be read safely: {path}") from error
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ContractError(f"file is not a regular file: {path}")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)


def open_directory_no_follow(path: Path) -> int:
    spec = _parse_output_path(path)
    parent_fd = _pin_parent(spec)
    try:
        try:
            descriptor = os.open(
                spec.leaf,
                _DIRECTORY_FLAGS | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
        except OSError as error:
            raise ContractError(f"directory cannot be opened safely: {path}") from error
        try:
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise ContractError(f"path is not a real directory: {path}")
        except (OSError, ContractError):
            os.close(descriptor)
            raise
        return descriptor
    finally:
        os.close(parent_fd)


def _create_pinned_bytes(
    output: _PinnedOutput, data: bytes, mode: int
) -> tuple[_FileIdentity, int]:
    try:
        descriptor = os.open(output.leaf, _CREATE_FLAGS, mode, dir_fd=output.parent_fd)
    except OSError as error:
        raise ContractError(f"create-only destination rejected: {output.path}") from error
    created: _FileIdentity | None = None
    try:
        created = _fstat_identity(descriptor, output.path)
        _write_all(descriptor, data)
        os.fsync(descriptor)
        return created, os.dup(descriptor)
    except (OSError, ContractError) as error:
        if created is None:
            _quarantine_unverified_output(output)
        else:
            _rollback_created_output(output, created)
        raise ContractError(f"create-only destination rejected: {output.path}") from error
    finally:
        os.close(descriptor)


def _quarantine_name() -> str:
    return f"{_QUARANTINE_PREFIX}{secrets.token_hex(16)}"


def _rename_to_quarantine(output: _PinnedOutput) -> str | None:
    for _ in range(16):
        quarantine = _quarantine_name()
        try:
            _require_absent_leaf(output.parent_fd, quarantine, output.path)
            os.rename(
                output.leaf,
                quarantine,
                src_dir_fd=output.parent_fd,
                dst_dir_fd=output.parent_fd,
            )
            return quarantine
        except FileNotFoundError:
            return None
        except FileExistsError:
            continue
        except OSError as error:
            raise ContractError(f"rollback quarantine failed for {output.path}") from error
    raise ContractError(f"rollback quarantine name collision for {output.path}")


def _open_quarantine_identity(output: _PinnedOutput, quarantine: str) -> _FileIdentity:
    try:
        descriptor = os.open(
            quarantine,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=output.parent_fd,
        )
    except OSError as error:
        raise ContractError(
            f"rollback quarantine cannot be verified for {output.path}: {quarantine}"
        ) from error
    try:
        return _fstat_identity(descriptor, output.path)
    finally:
        os.close(descriptor)


def _remove_quarantine(output: _PinnedOutput, quarantine: str) -> None:
    try:
        os.unlink(quarantine, dir_fd=output.parent_fd)
    except OSError as error:
        raise ContractError(
            f"rollback cleanup failed for {output.path}: preserved quarantine {quarantine}"
        ) from error


def _restore_quarantine(output: _PinnedOutput, quarantine: str) -> None:
    try:
        os.link(
            quarantine,
            output.leaf,
            src_dir_fd=output.parent_fd,
            dst_dir_fd=output.parent_fd,
            follow_symlinks=False,
        )
    except FileExistsError as error:
        raise ContractError(
            f"rollback restoration conflict for {output.path}: preserved quarantine {quarantine}"
        ) from error
    except OSError as error:
        raise ContractError(
            f"rollback restoration failed for {output.path}: preserved quarantine {quarantine}"
        ) from error
    _remove_quarantine(output, quarantine)


def _rollback_created_output(output: _PinnedOutput, identity: _FileIdentity) -> None:
    quarantine = _rename_to_quarantine(output)
    if quarantine is None:
        return
    quarantined_identity = _open_quarantine_identity(output, quarantine)
    if quarantined_identity == identity:
        _remove_quarantine(output, quarantine)
        return
    _restore_quarantine(output, quarantine)


def _quarantine_unverified_output(output: _PinnedOutput) -> None:
    quarantine = _rename_to_quarantine(output)
    if quarantine is None:
        return
    raise ContractError(
        f"created output identity unavailable for {output.path}: preserved quarantine {quarantine}"
    )


def _close_outputs(outputs: tuple[_PinnedOutput, ...]) -> None:
    for output in outputs:
        os.close(output.parent_fd)


def ensure_safe_parent(path: Path) -> None:
    output = _prepare_create_destination(path)
    try:
        pass
    finally:
        _close_outputs((output,))


def create_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Create one output with no-follow parents, absent leaf, and exclusive open."""
    output = _prepare_create_destination(path)
    try:
        _, identity_pin = _create_pinned_bytes(output, data, mode)
        os.close(identity_pin)
    finally:
        _close_outputs((output,))


def create_bytes_pair(first: BytesOutput, second: BytesOutput, mode: int = 0o600) -> None:
    """Create paired outputs atomically for ordinary failures.

    The portable contract is no-follow traversal, traversal rejection,
    occupied-leaf refusal, exclusive create, and deterministic paired-failure
    rollback. Hostile same-user namespace replacement after pinned-fd
    operations begin remains outside this helper's cross-platform guarantee.
    """
    first_path, first_data = first
    second_path, second_data = second
    first_spec = _parse_output_path(first_path)
    second_spec = _parse_output_path(second_path)
    first_output, second_output = _prepare_pair_outputs(first_spec, second_spec)
    try:
        first_identity, first_identity_pin = _create_pinned_bytes(
            first_output, first_data, mode
        )
        try:
            _, second_identity_pin = _create_pinned_bytes(
                second_output, second_data, mode
            )
            os.close(second_identity_pin)
        except ContractError:
            _rollback_created_output(first_output, first_identity)
            raise
        finally:
            os.close(first_identity_pin)
    finally:
        _close_outputs((first_output, second_output))


def _prepare_pair_outputs(
    first: _OutputSpec, second: _OutputSpec
) -> tuple[_PinnedOutput, _PinnedOutput]:
    if first.parent_parts == second.parent_parts:
        return _prepare_same_parent_pair(first, second)
    return _prepare_distinct_parent_pair(first, second)


def _prepare_same_parent_pair(
    first: _OutputSpec, second: _OutputSpec
) -> tuple[_PinnedOutput, _PinnedOutput]:
    if first.leaf == second.leaf:
        raise ContractError(f"create-only destination rejected: {first.path}")
    first_fd = _pin_parent(first)
    try:
        second_fd = os.dup(first_fd)
    except OSError:
        os.close(first_fd)
        raise
    first_output = _PinnedOutput(first.path, first_fd, first.leaf)
    second_output = _PinnedOutput(second.path, second_fd, second.leaf)
    try:
        _require_absent_leaf(first_output.parent_fd, first_output.leaf, first_output.path)
        _require_absent_leaf(second_output.parent_fd, second_output.leaf, second_output.path)
        return first_output, second_output
    except (OSError, ContractError):
        _close_outputs((first_output, second_output))
        raise


def _prepare_distinct_parent_pair(
    first: _OutputSpec, second: _OutputSpec
) -> tuple[_PinnedOutput, _PinnedOutput]:
    first_fd = _pin_parent(first)
    try:
        second_fd = _pin_parent(second)
    except (OSError, ContractError):
        os.close(first_fd)
        raise
    first_output = _PinnedOutput(first.path, first_fd, first.leaf)
    second_output = _PinnedOutput(second.path, second_fd, second.leaf)
    try:
        _require_absent_leaf(first_output.parent_fd, first_output.leaf, first_output.path)
        _require_absent_leaf(second_output.parent_fd, second_output.leaf, second_output.path)
        return first_output, second_output
    except (OSError, ContractError):
        _close_outputs((first_output, second_output))
        raise


def create_json(path: Path, value: JsonValue) -> None:
    create_bytes(path, canonical_bytes(value))


def file_record(
    root: str,
    base: Path,
    path: Path,
    *,
    role: str | None = None,
    data: bytes | None = None,
) -> dict[str, JsonValue]:
    validate_root(root)
    relative = os.path.relpath(os.fsencode(path), os.fsencode(base))
    decoded = decode_path(encode_path(relative))
    data = read_bytes_no_follow(path) if data is None else data
    record: dict[str, JsonValue] = {
        "path_b64": encode_path(decoded),
        "root": root,
        "sha256": digest(data),
        "size": len(data),
    }
    if role is not None:
        record["role"] = role
    return record


def read_file_record(record: JsonValue, roots: dict[str, Path]) -> tuple[Path, bytes]:
    if not isinstance(record, dict):
        raise ContractError("invalid evidence record")
    root = record.get("root")
    if not isinstance(root, str) or root not in roots:
        raise ContractError("unknown evidence record root")
    try:
        relative = decode_path(record.get("path_b64"))
        path = roots[root] / os.fsdecode(relative)
        data = read_bytes_no_follow(path)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise ContractError("evidence record cannot be read") from error
    if len(data) != record.get("size") or digest(data) != record.get("sha256"):
        raise ContractError(f"evidence changed: {path}")
    return path, data

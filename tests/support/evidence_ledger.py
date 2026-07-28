from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from evidence_json import (
    ContractError,
    JsonValue,
    canonical_bytes,
    create_bytes_pair,
    decode_path,
    digest,
    encode_path,
    file_record,
    load_json,
    parse_json_bytes,
    read_bytes_no_follow,
    read_file_record,
)

LEDGER_RELATIVE_PATH: Final = ".omo/start-work/ledger.jsonl"
LEDGER_RELATIVE_BYTES: Final = b".omo/start-work/ledger.jsonl"
PRODUCT_SCHEMA: Final = "agent-brain-implementation/v3"
HISTORICAL_PRODUCT_SCHEMAS: Final = frozenset({"agent-brain-implementation/v2"})
PRODUCT_SCOPE: Final = "product"
PRODUCT_EXCLUDED_PATHS: Final = (LEDGER_RELATIVE_PATH,)
_DIRECTORY_FLAGS: Final = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)


def product_excluded_absolute(root: Path) -> set[bytes]:
    return {os.fsencode(root) + b"/" + LEDGER_RELATIVE_BYTES}


_REQUIRED_PRIOR_PHASE: Final = {
    "wave-4-approval": None,
    "final-freeze": "wave-4-approval",
    "final-review": "final-freeze",
    "completion": "final-review",
}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_ledger_no_follow(impl_root: Path) -> bytes:
    root_fd = os.open(impl_root, _DIRECTORY_FLAGS | getattr(os, "O_NOFOLLOW", 0))
    current_fd = root_fd
    try:
        parts = LEDGER_RELATIVE_PATH.split("/")
        for part in parts[:-1]:
            next_fd = os.open(part, _DIRECTORY_FLAGS | getattr(os, "O_NOFOLLOW", 0), dir_fd=current_fd)
            previous_fd = current_fd
            try:
                os.close(previous_fd)
            except OSError as error:
                os.close(next_fd)
                current_fd = -1
                raise ContractError("ledger checkpoint path is not a regular file") from error
            current_fd = next_fd
        leaf_fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=current_fd)
        try:
            info = os.fstat(leaf_fd)
            if not stat.S_ISREG(info.st_mode):
                raise ContractError("ledger checkpoint path is not a regular file")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(leaf_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(leaf_fd)
    except OSError as error:
        raise ContractError("ledger checkpoint path is not a regular file") from error
    finally:
        if current_fd >= 0:
            os.close(current_fd)


def _validate_jsonl_suffix(data: bytes) -> int:
    if data == b"":
        return 0
    if not data.endswith(b"\n"):
        raise ContractError("ledger checkpoint suffix is incomplete")
    line_count = 0
    for raw_line in data.splitlines():
        line_count += 1
        try:
            value = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ContractError("ledger checkpoint suffix is malformed") from error
        if not isinstance(value, dict) or not isinstance(value.get("event"), str):
            raise ContractError("ledger checkpoint suffix event is missing")
    return line_count


def _record_path(record: JsonValue, evidence_root: Path) -> Path:
    path, _data = read_file_record(record, {"evidence": evidence_root})
    return path


def _verify_file_record(record: JsonValue, evidence_root: Path) -> tuple[Path, bytes]:
    return read_file_record(record, {"evidence": evidence_root})


def _planned_file_record(root: str, base: Path, path: Path, data: bytes) -> dict[str, JsonValue]:
    relative = os.path.relpath(os.fsencode(path), os.fsencode(base))
    decoded = decode_path(encode_path(relative))
    return {
        "path_b64": encode_path(decoded),
        "root": root,
        "sha256": digest(data),
        "size": len(data),
    }


def _prior_bytes(
    prior_checkpoint: Path | None,
    evidence_root: Path,
) -> tuple[dict[str, JsonValue] | None, bytes, bytes]:
    if prior_checkpoint is None:
        return None, b"", b""
    prior_data = read_bytes_no_follow(prior_checkpoint)
    prior = parse_json_bytes(prior_data, prior_checkpoint)
    data = verify_ledger_checkpoint(prior_checkpoint, evidence_root, value=prior)
    return prior, data, prior_data


def create_ledger_checkpoint(
    impl_root: Path,
    evidence_root: Path,
    output: Path,
    bytes_output: Path,
    prior_checkpoint: Path | None,
    phase: str = "manual",
    prior_phase: str | None = None,
) -> None:
    data = _read_ledger_no_follow(impl_root)
    prior, previous, prior_data = _prior_bytes(prior_checkpoint, evidence_root)
    if prior_phase is not None:
        if prior is None or prior.get("phase") != prior_phase:
            raise ContractError("ledger checkpoint prior phase mismatch")
    if not data.startswith(previous):
        raise ContractError("ledger checkpoint does not extend prior prefix")
    line_count = _validate_jsonl_suffix(data)
    suffix_line_count = _validate_jsonl_suffix(data[len(previous):])
    value: dict[str, JsonValue] = {
        "created_at": _now(),
        "ledger_bytes": _planned_file_record("evidence", evidence_root, bytes_output, data),
        "ledger_line_count": line_count,
        "ledger_path": LEDGER_RELATIVE_PATH,
        "ledger_sha256": digest(data),
        "ledger_size": len(data),
        "phase": phase,
        "prefix_sha256": digest(previous),
        "prior_checkpoint": None,
        "prior_checkpoint_sha256": None,
        "schema_version": "agent-brain-ledger-checkpoint/v1",
        "suffix_line_count": suffix_line_count,
    }
    if prior_checkpoint is not None and prior is not None:
        value["prior_checkpoint"] = file_record(
            "evidence",
            evidence_root,
            prior_checkpoint,
            data=prior_data,
        )
        value["prior_checkpoint_sha256"] = digest(prior_data)
    create_bytes_pair((bytes_output, data), (output, canonical_bytes(value)))


def verify_ledger_checkpoint(
    checkpoint: Path,
    evidence_root: Path,
    expected_phase: str | None = None,
    seen: set[bytes] | None = None,
    value: dict[str, JsonValue] | None = None,
) -> bytes:
    seen = set() if seen is None else seen
    checkpoint_key = os.fsencode(checkpoint)
    if checkpoint_key in seen:
        raise ContractError("ledger checkpoint cycle")
    seen.add(checkpoint_key)
    value = load_json(checkpoint) if value is None else value
    if value.get("schema_version") != "agent-brain-ledger-checkpoint/v1":
        raise ContractError("invalid ledger checkpoint schema")
    if expected_phase is not None and value.get("phase") != expected_phase:
        raise ContractError("ledger checkpoint phase mismatch")
    phase = value.get("phase")
    if not isinstance(phase, str):
        raise ContractError("ledger checkpoint phase mismatch")
    if value.get("ledger_path") != LEDGER_RELATIVE_PATH:
        raise ContractError("ledger checkpoint path mismatch")
    _bytes_path, data = _verify_file_record(value.get("ledger_bytes"), evidence_root)
    if value.get("ledger_sha256") != digest(data) or value.get("ledger_size") != len(data):
        raise ContractError("ledger checkpoint bytes mismatch")
    if value.get("ledger_line_count") != _validate_jsonl_suffix(data):
        raise ContractError("ledger checkpoint line count mismatch")
    prior_record = value.get("prior_checkpoint")
    required_prior = _REQUIRED_PRIOR_PHASE.get(phase, "manual")
    if prior_record is None:
        if required_prior is not None and phase != "manual":
            raise ContractError("ledger checkpoint prior phase mismatch")
        prior_bytes = b""
    else:
        if phase == "wave-4-approval":
            raise ContractError("ledger checkpoint prior phase mismatch")
        prior_path, prior_raw = _verify_file_record(prior_record, evidence_root)
        if prior_path == checkpoint:
            raise ContractError("ledger checkpoint cycle")
        if value.get("prior_checkpoint_sha256") != digest(prior_raw):
            raise ContractError("ledger checkpoint prior hash mismatch")
        prior = parse_json_bytes(prior_raw, prior_path)
        prior_bytes = verify_ledger_checkpoint(
            prior_path,
            evidence_root,
            required_prior if required_prior not in {"manual", None} else None,
            seen,
            prior,
        )
        if isinstance(required_prior, str) and required_prior != "manual" and prior.get("phase") != required_prior:
            raise ContractError("ledger checkpoint prior phase mismatch")
    if value.get("prefix_sha256") != digest(prior_bytes):
        raise ContractError("ledger checkpoint prefix hash mismatch")
    if not data.startswith(prior_bytes):
        raise ContractError("ledger checkpoint does not extend prior prefix")
    if value.get("suffix_line_count") != _validate_jsonl_suffix(data[len(prior_bytes):]):
        raise ContractError("ledger checkpoint suffix mismatch")
    return data

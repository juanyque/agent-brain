from __future__ import annotations

import base64
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from evidence_json import (
    ContractError,
    JsonValue,
    canonical_bytes,
    digest,
    open_directory_no_follow,
    parse_json_bytes,
    read_bytes_no_follow,
)


@dataclass(frozen=True, slots=True)
class PinnedFile:
    path: Path
    data: bytes


@dataclass(frozen=True, slots=True)
class PinnedJson:
    path: Path
    data: bytes
    value: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class PinnedDirectoryFile:
    path: str
    data: bytes


@dataclass(frozen=True, slots=True)
class PinnedDirectory:
    sha256: str
    files: tuple[PinnedDirectoryFile, ...]


def file_ref(path: Path) -> dict[str, JsonValue]:
    data = read_bytes_no_follow(path)
    return {"path": str(path), "sha256": digest(data), "size": len(data)}


def verify_file_ref(record: JsonValue) -> PinnedFile:
    if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
        raise ContractError("invalid file reference")
    path = Path(str(record["path"]))
    data = read_bytes_no_follow(path)
    if len(data) != record["size"] or digest(data) != record["sha256"]:
        raise ContractError(f"file reference changed: {path}")
    return PinnedFile(path, data)


def _provenance_schema(path: Path, role: str, data: bytes) -> str:
    try:
        value = parse_json_bytes(data, path)
    except ContractError:
        if role == "reviewed-draft":
            return "agent-brain-reviewed-draft/markdown"
        return "application/octet-stream"
    schema = value.get("schema_version")
    if not isinstance(schema, str):
        raise ContractError("provenance artifact schema is missing")
    if data != canonical_bytes(value):
        raise ContractError("provenance artifact is not canonical")
    return schema


def verify_json_ref(record: JsonValue) -> PinnedJson:
    pinned = verify_file_ref(record)
    return PinnedJson(pinned.path, pinned.data, parse_json_bytes(pinned.data, pinned.path))


def pin_json(path: Path) -> PinnedJson:
    data = read_bytes_no_follow(path)
    return PinnedJson(path, data, parse_json_bytes(data, path))


def pin_file(path: Path) -> PinnedFile:
    return PinnedFile(path, read_bytes_no_follow(path))


def provenance_ref(path: Path, root: str, role: str) -> dict[str, JsonValue]:
    data = read_bytes_no_follow(path)
    return {
        "hash": digest(data),
        "path": str(path),
        "role": role,
        "root": root,
        "schema": _provenance_schema(path, role, data),
        "size": len(data),
    }


def verify_provenance_ref(record: JsonValue, root: str, role: str) -> PinnedFile:
    if not isinstance(record, dict) or set(record) != {"hash", "path", "role", "root", "schema", "size"}:
        raise ContractError("invalid approval provenance record")
    if record["root"] != root or record["role"] != role:
        raise ContractError("approval provenance role mismatch")
    path = Path(str(record["path"]))
    data = read_bytes_no_follow(path)
    if len(data) != record["size"] or digest(data) != record["hash"]:
        raise ContractError(f"approval provenance changed: {path}")
    if _provenance_schema(path, role, data) != record["schema"]:
        raise ContractError("approval provenance schema mismatch")
    return PinnedFile(path, data)


def _read_descriptor(descriptor: int, path: Path) -> bytes:
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ContractError(f"sidecar is not a regular file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    except OSError as error:
        raise ContractError(f"sidecar cannot be read safely: {path}") from error


def _pin_directory_rows(
    descriptor: int,
    root: Path,
    relative: str,
    rows: list[dict[str, JsonValue]],
    files: list[PinnedDirectoryFile],
) -> None:
    try:
        with os.scandir(descriptor) as iterator:
            names = sorted(entry.name for entry in iterator)
    except OSError as error:
        raise ContractError(f"sidecar directory cannot be scanned safely: {root}") from error
    for name in names:
        path = root / relative / name
        child_relative = name if not relative else f"{relative}/{name}"
        try:
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except OSError as error:
            raise ContractError(f"sidecar entry cannot be inspected safely: {path}") from error
        if stat.S_ISLNK(info.st_mode):
            raise ContractError(f"state sidecars contain symlink: {path}")
        if stat.S_ISDIR(info.st_mode):
            try:
                child_fd = os.open(
                    name,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
            except OSError as error:
                raise ContractError(f"sidecar directory cannot be opened safely: {path}") from error
            try:
                opened_info = os.fstat(child_fd)
                if not stat.S_ISDIR(opened_info.st_mode):
                    raise ContractError(f"sidecar is not a real directory: {path}")
                rows.append(
                    {
                        "mode": stat.S_IMODE(opened_info.st_mode),
                        "path": child_relative,
                        "type": "directory",
                    }
                )
                _pin_directory_rows(child_fd, root, child_relative, rows, files)
            finally:
                os.close(child_fd)
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ContractError(f"state sidecars contain unsupported entry: {path}")
        try:
            child_fd = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
        except OSError as error:
            raise ContractError(f"sidecar cannot be opened safely: {path}") from error
        try:
            opened_info = os.fstat(child_fd)
            if not stat.S_ISREG(opened_info.st_mode):
                raise ContractError(f"sidecar is not a regular file: {path}")
            data = _read_descriptor(child_fd, path)
        finally:
            os.close(child_fd)
        rows.append(
            {
                "mode": stat.S_IMODE(opened_info.st_mode),
                "path": child_relative,
                "sha256": digest(data),
                "size": len(data),
                "type": "file",
            }
        )
        files.append(PinnedDirectoryFile(child_relative, data))


def pin_directory(root: Path) -> PinnedDirectory:
    rows: list[dict[str, JsonValue]] = []
    files: list[PinnedDirectoryFile] = []
    descriptor = open_directory_no_follow(root)
    try:
        _pin_directory_rows(descriptor, root, "", rows, files)
    finally:
        os.close(descriptor)
    return PinnedDirectory(digest(canonical_bytes(rows)), tuple(files))


def directory_sha(root: Path) -> str:
    return pin_directory(root).sha256


def state_ref(state: Path, sidecars: Path) -> dict[str, JsonValue]:
    record = file_ref(state)
    record["sidecar_dir"] = str(sidecars)
    record["sidecars_sha256"] = directory_sha(sidecars)
    return record


def verify_state_ref(record: JsonValue) -> tuple[dict[str, JsonValue], Path]:
    if not isinstance(record, dict) or set(record) != {
        "path",
        "sha256",
        "sidecar_dir",
        "sidecars_sha256",
        "size",
    }:
        raise ContractError("invalid state reference")
    state = verify_json_ref(
        {"path": record["path"], "sha256": record["sha256"], "size": record["size"]}
    )
    sidecars = Path(str(record["sidecar_dir"]))
    pinned_sidecars = pin_directory(sidecars)
    if pinned_sidecars.sha256 != record["sidecars_sha256"]:
        raise ContractError("state sidecars changed")
    sidecar_files = {item.path: item.data for item in pinned_sidecars.files}
    names = set()
    for item in state.value.get("sidecars", []):
        if not isinstance(item, dict):
            raise ContractError("invalid state sidecar item")
        raw = base64.b64decode(str(item["path_b64"]), validate=True)
        name = raw.decode("utf-8")
        if name in names:
            raise ContractError("duplicate state sidecar")
        names.add(name)
        data = sidecar_files.get(name)
        if data is None:
            raise ContractError("state sidecar is missing")
        if len(data) != item["size"] or digest(data) != item["sha256"]:
            raise ContractError("state sidecar changed")
    return state.value, sidecars


def plan_checklist(path: Path) -> tuple[list[int], list[int]]:
    return plan_checklist_bytes(read_bytes_no_follow(path), path)


def plan_checklist_bytes(data: bytes, path: Path) -> tuple[list[int], list[int]]:
    checked: set[int] = set()
    unchecked: set[int] = set()
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ContractError(f"invalid plan text: {path}") from error
    for line in lines:
        match = re.search(
            r"- \[([ xX])\].*?(?:todo|task)\s*-?\s*(\d+)|- \[([ xX])\]\s*(\d+)\.",
            line,
            re.IGNORECASE,
        ) or re.match(r"\s*- \[([ xX])\]\s*(\d+)\b", line)
        if match is None:
            continue
        marker = match.group(1) or match.group(3)
        raw = match.group(2) or match.group(4)
        target = checked if marker.lower() == "x" else unchecked
        target.add(int(raw))
    if checked & unchecked:
        raise ContractError("plan checklist contains duplicate todo states")
    return sorted(checked), sorted(unchecked)


def verify_evidence_records(value: JsonValue, evidence_root: Path) -> int:
    total = 0
    if isinstance(value, dict):
        if {"root", "path_b64", "sha256", "size"} <= set(value):
            if value["root"] != "evidence":
                raise ContractError("unsupported nested evidence root")
            raw = base64.b64decode(str(value["path_b64"]), validate=True)
            if not raw or raw.startswith(b"/") or b".." in raw.split(b"/"):
                raise ContractError("unsafe nested evidence path")
            path = evidence_root / raw.decode("utf-8")
            data = read_bytes_no_follow(path)
            if len(data) != value["size"] or digest(data) != value["sha256"]:
                raise ContractError(f"nested evidence changed: {path}")
            total += 1
        for item in value.values():
            total += verify_evidence_records(item, evidence_root)
    elif isinstance(value, list):
        for item in value:
            total += verify_evidence_records(item, evidence_root)
    return total

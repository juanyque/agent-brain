from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Final

from evidence_json import (
    ContractError,
    JsonValue,
    canonical_bytes,
    digest,
    encode_path,
    load_json,
    read_bytes_no_follow,
)
from evidence_publication import StatePublication, publish_state_capture
from evidence_tree import scan_tree


COMMANDS: Final = (
    ("symbolic-head", ("symbolic-ref", "-q", "HEAD")),
    ("commit", ("rev-parse", "--verify", "HEAD")),
    ("status", ("status", "--porcelain=v1", "-z")),
    ("index", ("ls-files", "--stage", "-z")),
    ("refs", ("for-each-ref", "--format=%(refname)%00%(objectname)%00")),
    ("reflogs", ("reflog", "show", "--all", "--format=%H%x00%gD%x00%gs%x00")),
)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"},
        capture_output=True,
        check=False,
    )


def _git_path(root: Path, *arguments: str) -> Path:
    result = _git(root, "rev-parse", *arguments)
    if result.returncode != 0:
        raise ContractError(f"not a Git repository: {root}")
    path = Path(os.fsdecode(result.stdout.rstrip(b"\n")))
    return path if path.is_absolute() else root / path


def _tree_digest(entries: list[dict[str, JsonValue]]) -> str:
    return digest(canonical_bytes(entries))


def _semantic_index(data: bytes) -> bytes:
    records: list[dict[str, JsonValue]] = []
    for entry in data.split(b"\0"):
        if not entry:
            continue
        try:
            header, path = entry.split(b"\t", 1)
            mode, blob, stage = header.split(b" ", 2)
        except ValueError as error:
            raise ContractError("invalid git index sidecar") from error
        records.append(
            {
                "blob": blob.decode("ascii").lower(),
                "mode": mode.decode("ascii"),
                "path_b64": encode_path(path),
                "stage": int(stage.decode("ascii")),
            }
        )
    records.sort(
        key=lambda record: (
            __import__("base64").b64decode(str(record["path_b64"]), validate=True),
            str(record["mode"]),
            str(record["blob"]),
            int(record["stage"]),
        )
    )
    return canonical_bytes(records)


def _sidecar_data(role: str, data: bytes) -> bytes:
    if role == "index":
        return _semantic_index(data)
    return data


def capture_state(kind: str, root: Path, output: Path, sidecar_dir: Path) -> None:
    if kind not in {"source", "brain"}:
        raise ContractError("state kind must be source or brain")
    resolved_root = root.resolve()
    git_dir = _git_path(resolved_root, "--absolute-git-dir").resolve()
    common_dir = _git_path(resolved_root, "--git-common-dir").resolve()
    index_path = _git_path(resolved_root, "--git-path", "index").resolve()
    excluded = {
        os.fsencode(path)
        for path in {git_dir, common_dir, index_path}
        if path == resolved_root or resolved_root in path.parents
    }
    working = scan_tree(resolved_root, excluded)
    admin_roots = sorted({git_dir, common_dir}, key=lambda path: os.fsencode(path))
    admin = []
    for path in admin_roots:
        entries = scan_tree(path, excluded)
        admin.append(
            {
                "entries": entries,
                "path_b64": encode_path(os.fsencode(str(path))),
                "sha256": _tree_digest(entries),
            }
        )
    sidecars: list[dict[str, JsonValue]] = []
    sidecar_outputs = []
    for index, (role, args) in enumerate(COMMANDS, start=1):
        result = _git(resolved_root, *args)
        if result.returncode not in {0, 1}:
            raise ContractError(f"Git sidecar command failed: {role}")
        data = _sidecar_data(role, result.stdout)
        path = sidecar_dir / f"{index}-{role}.bin"
        sidecar_outputs.append((path, data))
        sidecars.append(
            {
                "path_b64": encode_path(os.fsencode(path.name)),
                "role": role,
                "root": kind,
                "sha256": digest(data),
                "size": len(data),
            }
        )
    value = {
        "admin": admin,
        "kind": kind,
        "schema_version": "agent-brain-state/v1",
        "sidecars": sidecars,
        "working": working,
    }
    publish_state_capture(
        StatePublication(output, sidecar_dir, tuple(sidecar_outputs), canonical_bytes(value))
    )


def compare_state(
    left: Path,
    left_sidecars: Path,
    right: Path,
    right_sidecars: Path,
) -> bool:
    left_value = load_json(left)
    right_value = load_json(right)
    return compare_state_values(left_value, left_sidecars, right_value, right_sidecars)


def compare_state_values(
    left_value: dict[str, JsonValue],
    left_sidecars: Path,
    right_value: dict[str, JsonValue],
    right_sidecars: Path,
) -> bool:
    if left_value != right_value:
        return False
    for record in left_value.get("sidecars", []):
        if not isinstance(record, dict):
            raise ContractError("invalid sidecar record")
        name = __import__("base64").b64decode(record["path_b64"], validate=True)
        if (os.fsencode(left_sidecars) + b"/" + name) != (
            os.fsencode(right_sidecars) + b"/" + name
        ):
            left_data = read_bytes_no_follow(
                Path(os.fsdecode(os.fsencode(left_sidecars) + b"/" + name))
            )
            right_data = read_bytes_no_follow(
                Path(os.fsdecode(os.fsencode(right_sidecars) + b"/" + name))
            )
            if left_data != right_data:
                return False
    return True

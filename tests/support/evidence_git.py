from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Final

from evidence_json import (
    BytesOutput,
    ContractError,
    JsonValue,
    canonical_bytes,
    decode_path,
    digest,
    encode_path,
    load_json,
    read_bytes_no_follow,
)
from evidence_publication import StatePublication, publish_state_capture

GIT_STATE_SCHEMA: Final = "agent-brain-implementation-git-state/v1"
CONTROLLED_ENVIRONMENT: Final = {
    "GIT_OPTIONAL_LOCKS": "0",
    "LANG": "C",
    "LC_ALL": "C",
    "PYTHONDONTWRITEBYTECODE": "1",
}
COMMANDS: Final = (
    ("symbolic-head", ("symbolic-ref", "-q", "HEAD")),
    ("commit", ("rev-parse", "--verify", "HEAD")),
    ("status", ("status", "--porcelain=v1", "-z")),
    ("index", ("ls-files", "--stage", "-z")),
    ("refs", ("for-each-ref", "--format=%(refname)%00%(objectname)%00")),
    ("reflogs", ("reflog", "show", "--all", "--format=%H%x00%gD%x00%gs%x00")),
)


def controlled_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    result = {"PATH": os.environ.get("PATH", os.defpath), **CONTROLLED_ENVIRONMENT}
    if extra is not None:
        result.update(extra)
    return result


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        env=controlled_environment(),
        capture_output=True,
        check=False,
    )


def _git_path(root: Path, *arguments: str) -> Path | None:
    result = _git(root, "rev-parse", *arguments)
    if result.returncode != 0:
        return None
    raw = result.stdout.rstrip(b"\n")
    if b"\0" in raw:
        return None
    path = Path(os.fsdecode(raw))
    return path if path.is_absolute() else root / path


def git_admin_paths(root: Path) -> tuple[Path, Path, Path] | None:
    resolved = root.resolve()
    git_dir = _git_path(resolved, "--absolute-git-dir")
    common_dir = _git_path(resolved, "--git-common-dir")
    index_path = _git_path(resolved, "--git-path", "index")
    if git_dir is None or common_dir is None or index_path is None:
        return None
    return git_dir.resolve(), common_dir.resolve(), index_path.resolve()


def git_admin_excluded_absolute(root: Path) -> set[bytes]:
    resolved = root.resolve()
    paths = git_admin_paths(resolved)
    excluded: set[bytes] = set()
    marker = resolved / ".git"
    if os.path.lexists(marker):
        excluded.add(os.fsencode(marker))
    if paths is None:
        return excluded
    for path in paths:
        if path == resolved or resolved in path.parents:
            excluded.add(os.fsencode(path))
    return excluded


def scan_git_admin_path(root: Path, excluded: set[bytes] | None = None) -> list[dict[str, JsonValue]]:
    base = os.fsencode(root)
    excluded = excluded or set()
    entries: list[dict[str, JsonValue]] = []

    def visit(relative: bytes) -> None:
        absolute = base + (b"/" + relative if relative else b"")
        with os.scandir(absolute) as iterator:
            children = sorted(iterator, key=lambda item: os.fsencode(item.name))
        for child in children:
            name = os.fsencode(child.name)
            path = name if not relative else relative + b"/" + name
            absolute_child = base + b"/" + path
            if absolute_child in excluded:
                continue
            info = child.stat(follow_symlinks=False)
            common = {"mode": stat.S_IMODE(info.st_mode), "path_b64": encode_path(path)}
            if stat.S_ISDIR(info.st_mode):
                entries.append({**common, "type": "directory"})
                visit(path)
            elif stat.S_ISLNK(info.st_mode):
                target = os.readlink(absolute_child)
                target_bytes = target if isinstance(target, bytes) else os.fsencode(target)
                entries.append({**common, "target_b64": encode_path(target_bytes), "type": "symlink"})
            elif stat.S_ISREG(info.st_mode):
                data = read_bytes_no_follow(Path(os.fsdecode(absolute_child)))
                entries.append({**common, "sha256": digest(data), "size": len(data), "type": "file"})
            else:
                raise ContractError(f"unsupported Git admin entry: {os.fsdecode(path)}")

    visit(b"")
    return sorted(entries, key=lambda entry: decode_path(entry["path_b64"]))


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
            decode_path(record["path_b64"]),
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


def capture_git_state(root: Path, output: Path, sidecar_dir: Path) -> None:
    resolved = root.resolve()
    paths = git_admin_paths(resolved)
    admin: list[dict[str, JsonValue]] = []
    sidecars: list[dict[str, JsonValue]] = []
    sidecar_outputs: list[BytesOutput] = []
    if paths is not None:
        git_dir, common_dir, index_path = paths
        excluded = {os.fsencode(index_path)}
        for path in sorted({git_dir, common_dir}, key=lambda item: os.fsencode(item)):
            entries = scan_git_admin_path(path, excluded)
            try:
                recorded_path = os.fsencode(path.relative_to(resolved))
            except ValueError:
                recorded_path = os.fsencode(str(path))
            admin.append(
                {
                    "entries": entries,
                    "path_b64": encode_path(recorded_path),
                    "sha256": _tree_digest(entries),
                }
            )
        for index, (role, args) in enumerate(COMMANDS, start=1):
            result = _git(resolved, *args)
            if result.returncode not in {0, 1}:
                raise ContractError(f"Git sidecar command failed: {role}")
            data = _sidecar_data(role, result.stdout)
            path = sidecar_dir / f"{index}-{role}.bin"
            sidecar_outputs.append((path, data))
            sidecars.append(
                {
                    "path_b64": encode_path(os.fsencode(path.name)),
                    "role": role,
                    "root": "implementation",
                    "sha256": digest(data),
                    "size": len(data),
                }
            )
    value = {
        "admin": admin,
        "schema_version": GIT_STATE_SCHEMA,
        "sidecars": sidecars,
    }
    publish_state_capture(
        StatePublication(output, sidecar_dir, tuple(sidecar_outputs), canonical_bytes(value))
    )


def git_state_sha_from_manifest(manifest: Path) -> str:
    return digest(canonical_bytes(load_json(manifest)))


def git_state_sha(root: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="implementation-git-state-") as raw:
        base = Path(raw)
        manifest = base / "git-state.json"
        sidecars = base / "git-state-sidecars"
        capture_git_state(root, manifest, sidecars)
        return git_state_sha_from_manifest(manifest)


def verify_git_state(root: Path, manifest: Path, sidecar_dir: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="implementation-git-verify-") as raw:
        base = Path(raw)
        actual_manifest = base / "git-state.json"
        actual_sidecars = base / "git-state-sidecars"
        capture_git_state(root, actual_manifest, actual_sidecars)
        actual = load_json(actual_manifest)
        expected = load_json(manifest)
        if actual != expected:
            raise ContractError("implementation Git state mismatch")
        for record in expected.get("sidecars", []):
            if not isinstance(record, dict):
                raise ContractError("invalid implementation Git sidecar")
            name = os.fsdecode(decode_path(record.get("path_b64")))
            if read_bytes_no_follow(actual_sidecars / name) != read_bytes_no_follow(sidecar_dir / name):
                raise ContractError("implementation Git sidecar mismatch")

from __future__ import annotations

import io
import os
import stat
import subprocess
import tarfile
from pathlib import Path

from evidence_json import (
    ContractError,
    JsonValue,
    create_bytes,
    create_json,
    decode_path,
    digest,
    encode_path,
    load_json,
    read_bytes_no_follow,
    validate_manifest,
    validate_root,
)
from evidence_git import (
    capture_git_state,
    git_admin_excluded_absolute,
    git_state_sha_from_manifest,
    verify_git_state,
)
from evidence_git_archive import (
    create_git_reconstruction_archive,
    reconstruct_git_archive_bytes,
)
from evidence_ledger import (
    HISTORICAL_PRODUCT_SCHEMAS,
    PRODUCT_EXCLUDED_PATHS,
    PRODUCT_SCHEMA,
    PRODUCT_SCOPE,
    product_excluded_absolute,
)


def scan_tree(root: Path, excluded: set[bytes] | None = None) -> list[dict[str, JsonValue]]:
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
                entries.append(
                    {**common, "sha256": digest(data), "size": len(data), "type": "file"}
                )
            else:
                raise ContractError(f"unsupported filesystem entry: {os.fsdecode(path)}")

    visit(b"")
    return sorted(entries, key=lambda entry: decode_path(entry["path_b64"]))


def _blobs(root: Path, entries: list[dict[str, JsonValue]]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    base = os.fsencode(root)
    for entry in entries:
        if entry["type"] != "file":
            continue
        path = base + b"/" + decode_path(entry["path_b64"])
        data = read_bytes_no_follow(Path(os.fsdecode(path)))
        expected = entry["sha256"]
        if digest(data) != expected:
            raise ContractError("file changed during capture")
        result[str(expected)] = data
    return result


def create_archive(path: Path, blobs: dict[str, bytes]) -> None:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for sha256 in sorted(blobs):
            data = blobs[sha256]
            info = tarfile.TarInfo(f"blobs/{sha256}")
            info.size = len(data)
            info.mode = 0o600
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    member_bytes = sum(512 + ((len(data) + 511) // 512) * 512 for data in blobs.values())
    create_bytes(path, output.getvalue()[: member_bytes + 1024])


def git_status(root: Path) -> bytes:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=root,
        env={
            "GIT_OPTIONAL_LOCKS": "0",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": os.environ.get("PATH", os.defpath),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else b""


def capture_worktree(root: Path, archive: Path, manifest: Path, root_name: str) -> None:
    validate_root(root_name)
    root = root.resolve()
    product_scope = root_name == "implementation"
    excluded = product_excluded_absolute(root) | git_admin_excluded_absolute(root) if product_scope else None
    entries = scan_tree(root, excluded)
    status = git_status(root)
    value = {
        "entries": entries,
        "git_status_sha256": digest(status),
        "root": root_name,
        "schema_version": PRODUCT_SCHEMA if product_scope else "agent-brain-tree/v1",
    }
    if product_scope:
        git_manifest = manifest.with_suffix(".git-state.json")
        git_sidecars = manifest.with_suffix(".git-state-sidecars")
        git_archive = archive.with_suffix(".git.tar")
        capture_git_state(root, git_manifest, git_sidecars)
        git_archive_data = create_git_reconstruction_archive(root, git_archive)
        value["excluded_orchestration_paths"] = list(PRODUCT_EXCLUDED_PATHS)
        value["git_administration"] = {
            "reconstruction_archive": git_archive.name,
            "reconstruction_archive_sha256": digest(git_archive_data),
            "state_manifest": git_manifest.name,
            "state_sha256": git_state_sha_from_manifest(git_manifest),
            "state_sidecars": git_sidecars.name,
        }
        value["scope"] = PRODUCT_SCOPE
    create_archive(archive, _blobs(root, entries))
    create_json(manifest, value)


def _product_manifest(value: dict[str, JsonValue]) -> bool:
    schema = value.get("schema_version")
    if schema not in {PRODUCT_SCHEMA, *HISTORICAL_PRODUCT_SCHEMAS}:
        return False
    if value.get("root") != "implementation":
        raise ContractError("implementation manifest root mismatch")
    if value.get("scope") != PRODUCT_SCOPE:
        raise ContractError("implementation manifest scope mismatch")
    if value.get("excluded_orchestration_paths") != list(PRODUCT_EXCLUDED_PATHS):
        raise ContractError("implementation manifest exclusions mismatch")
    if schema == PRODUCT_SCHEMA:
        git = value.get("git_administration")
        if not isinstance(git, dict):
            raise ContractError("implementation manifest Git state is missing")
    return True


def _archive_blobs(data: bytes) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for member in archive.getmembers():
                if not member.isfile() or not member.name.startswith("blobs/"):
                    raise ContractError("archive contains a non-blob member")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ContractError("archive blob is unreadable")
                data = stream.read()
                sha256 = member.name.removeprefix("blobs/")
                if digest(data) != sha256 or sha256 in result:
                    raise ContractError("archive blob hash mismatch")
                result[sha256] = data
    except (OSError, tarfile.TarError) as error:
        raise ContractError(f"invalid archive: {error}") from error
    return result


def materialize(manifest_path: Path, archive_path: Path, output: Path) -> None:
    manifest = load_json(manifest_path)
    product_scope = _product_manifest(manifest)
    validate_manifest(manifest)
    if os.path.lexists(output):
        raise ContractError("materialization destination already exists")
    output.mkdir(mode=0o700)
    blobs = _archive_blobs(read_bytes_no_follow(archive_path))
    base = os.fsencode(output)
    try:
        for entry in manifest["entries"]:
            path = base + b"/" + decode_path(entry["path_b64"])
            kind = entry["type"]
            if kind == "directory":
                os.mkdir(path, entry["mode"])
            elif kind == "file":
                data = blobs[str(entry["sha256"])]
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, entry["mode"])
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(data)
            elif kind == "symlink":
                os.symlink(
                    __import__("base64").b64decode(entry["target_b64"], validate=True), path
                )
            else:
                raise ContractError("unknown entry type")
    except (KeyError, OSError, ValueError) as error:
        raise ContractError(f"materialization failed: {error}") from error
    if product_scope and manifest.get("schema_version") == PRODUCT_SCHEMA:
        git = manifest.get("git_administration")
        if not isinstance(git, dict):
            raise ContractError("implementation manifest Git state is missing")
        archive_name = git.get("reconstruction_archive")
        if not isinstance(archive_name, str):
            raise ContractError("implementation Git reconstruction archive is missing")
        reconstruction_data = read_bytes_no_follow(manifest_path.parent / archive_name)
        if digest(reconstruction_data) != git.get("reconstruction_archive_sha256"):
            raise ContractError("implementation Git reconstruction archive changed")
        reconstruct_git_archive_bytes(reconstruction_data, output)


def verify_materialized(manifest_path: Path, root: Path) -> None:
    manifest = load_json(manifest_path)
    root = root.resolve()
    product_scope = _product_manifest(manifest)
    validate_manifest(manifest)
    excluded = (
        product_excluded_absolute(root) | git_admin_excluded_absolute(root)
        if product_scope and manifest.get("schema_version") == PRODUCT_SCHEMA
        else None
    )
    entries = scan_tree(root, excluded)
    if entries != manifest["entries"]:
        raise ContractError("materialized tree differs from manifest")
    if product_scope and manifest.get("schema_version") == PRODUCT_SCHEMA:
        git = manifest.get("git_administration")
        if not isinstance(git, dict):
            raise ContractError("implementation manifest Git state is missing")
        manifest_name = git.get("state_manifest")
        sidecars_name = git.get("state_sidecars")
        if not isinstance(manifest_name, str) or not isinstance(sidecars_name, str):
            raise ContractError("implementation Git state paths are missing")
        verify_git_state(root, manifest_path.parent / manifest_name, manifest_path.parent / sidecars_name)

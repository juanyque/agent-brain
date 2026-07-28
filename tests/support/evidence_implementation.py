from __future__ import annotations

import io
import tempfile
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from evidence_closure_records import PinnedFile, PinnedJson, pin_file, pin_json
from evidence_json import ContractError, JsonValue, canonical_bytes, decode_path, digest, validate_manifest
from evidence_git import git_admin_excluded_absolute, git_state_sha, git_state_sha_from_manifest, verify_git_state
from evidence_ledger import (
    HISTORICAL_PRODUCT_SCHEMAS,
    PRODUCT_EXCLUDED_PATHS,
    PRODUCT_SCHEMA,
    PRODUCT_SCOPE,
    product_excluded_absolute,
)
from evidence_tree import capture_worktree, materialize, scan_tree, verify_materialized


@dataclass(frozen=True, slots=True)
class ImplementationSnapshot:
    manifest: PinnedJson
    archive: PinnedFile
    sha256: str
    git_state_sha256: str | None = None


def implementation_sha(root: Path) -> str:
    root = root.resolve()
    excluded = product_excluded_absolute(root) | git_admin_excluded_absolute(root)
    return digest(canonical_bytes(scan_tree(root, excluded)))


def implementation_git_state_sha(root: Path) -> str:
    return git_state_sha(root)


def _pinned_manifest(manifest: Path | PinnedJson) -> PinnedJson:
    match manifest:
        case Path():
            return pin_json(manifest)
        case PinnedJson():
            return manifest
        case unreachable:
            assert_never(unreachable)


def _pinned_archive(archive: Path | PinnedFile) -> PinnedFile:
    match archive:
        case Path():
            return pin_file(archive)
        case PinnedFile():
            return archive
        case unreachable:
            assert_never(unreachable)


def _implementation_manifest_entries(manifest: PinnedJson) -> tuple[list[JsonValue], bool]:
    value = manifest.value
    schema = value.get("schema_version")
    if schema not in {"agent-brain-tree/v1", PRODUCT_SCHEMA, *HISTORICAL_PRODUCT_SCHEMAS}:
        raise ContractError("invalid implementation manifest schema")
    if value.get("root") != "implementation":
        raise ContractError("implementation manifest root mismatch")
    if schema in {PRODUCT_SCHEMA, *HISTORICAL_PRODUCT_SCHEMAS}:
        if value.get("scope") != PRODUCT_SCOPE:
            raise ContractError("implementation manifest scope mismatch")
        if value.get("excluded_orchestration_paths") != list(PRODUCT_EXCLUDED_PATHS):
            raise ContractError("implementation manifest exclusions mismatch")
        if schema == PRODUCT_SCHEMA:
            git = value.get("git_administration")
            if not isinstance(git, dict):
                raise ContractError("implementation manifest Git state is missing")
    validate_manifest(value)
    entries = value.get("entries")
    if not isinstance(entries, list):
        raise ContractError("implementation manifest entries must be an array")
    return entries, schema in {PRODUCT_SCHEMA, *HISTORICAL_PRODUCT_SCHEMAS}


def manifest_implementation_git_sha(manifest: Path | PinnedJson) -> str | None:
    pinned = _pinned_manifest(manifest)
    value = pinned.value
    if value.get("schema_version") != PRODUCT_SCHEMA:
        return None
    git = value.get("git_administration")
    if not isinstance(git, dict):
        raise ContractError("implementation manifest Git state is missing")
    state_manifest = git.get("state_manifest")
    if not isinstance(state_manifest, str):
        raise ContractError("implementation Git state manifest is missing")
    actual = git_state_sha_from_manifest(pinned.path.parent / state_manifest)
    expected = git.get("state_sha256")
    if actual != expected:
        raise ContractError("implementation Git state hash mismatch")
    return actual


def manifest_implementation_sha(manifest: Path | PinnedJson) -> str:
    entries, _product = _implementation_manifest_entries(_pinned_manifest(manifest))
    return digest(canonical_bytes(entries))


def _archive_blob(archive: PinnedFile, sha256: str) -> bytes:
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.data), mode="r:") as tar:
            member = tar.getmember(f"blobs/{sha256}")
            stream = tar.extractfile(member)
            if stream is None:
                raise ContractError("implementation archive blob is unreadable")
            data = stream.read()
    except (KeyError, OSError, tarfile.TarError) as error:
        raise ContractError("implementation archive blob is missing") from error
    if digest(data) != sha256:
        raise ContractError("implementation archive blob hash mismatch")
    return data


def _verify_archive_blobs(manifest: PinnedJson, archive: PinnedFile) -> None:
    entries, _product = _implementation_manifest_entries(manifest)
    for entry in entries:
        if not isinstance(entry, dict):
            raise ContractError("implementation manifest entry must be an object")
        if entry.get("type") == "file":
            sha = entry.get("sha256")
            if not isinstance(sha, str):
                raise ContractError("implementation file hash is missing")
            _archive_blob(archive, sha)


def verify_implementation_snapshot(
    manifest: Path | PinnedJson,
    archive: Path | PinnedFile,
    expected_sha256: str,
) -> None:
    pinned_manifest = _pinned_manifest(manifest)
    pinned_archive = _pinned_archive(archive)
    if manifest_implementation_sha(pinned_manifest) != expected_sha256:
        raise ContractError("implementation manifest hash mismatch")
    manifest_implementation_git_sha(pinned_manifest)
    _verify_archive_blobs(pinned_manifest, pinned_archive)


def verify_implementation_git_state(root: Path, manifest: Path | PinnedJson) -> None:
    pinned = _pinned_manifest(manifest)
    value = pinned.value
    if value.get("schema_version") != PRODUCT_SCHEMA:
        return
    git = value.get("git_administration")
    if not isinstance(git, dict):
        raise ContractError("implementation manifest Git state is missing")
    state_manifest = git.get("state_manifest")
    sidecars = git.get("state_sidecars")
    if not isinstance(state_manifest, str) or not isinstance(sidecars, str):
        raise ContractError("implementation Git state paths are missing")
    verify_git_state(root, pinned.path.parent / state_manifest, pinned.path.parent / sidecars)


def active_plan_sha_from_snapshot(
    manifest: Path | PinnedJson,
    archive: Path | PinnedFile,
) -> str:
    pinned_manifest = _pinned_manifest(manifest)
    pinned_archive = _pinned_archive(archive)
    entries, _product = _implementation_manifest_entries(pinned_manifest)
    active_path = b".omo/plans/agent-brain-operating-model.md"
    matches: list[dict[str, JsonValue]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ContractError("implementation manifest entry must be an object")
        if decode_path(entry.get("path_b64")) == active_path:
            matches.append(entry)
    if len(matches) != 1:
        raise ContractError("implementation active plan entry mismatch")
    if matches[0].get("type") != "file":
        raise ContractError("implementation active plan entry must be a file")
    expected_sha = matches[0].get("sha256")
    if not isinstance(expected_sha, str):
        raise ContractError("implementation active plan hash is missing")
    data = _archive_blob(pinned_archive, expected_sha)
    actual_sha = digest(data)
    if actual_sha != expected_sha:
        raise ContractError("implementation active plan blob mismatch")
    return actual_sha


def implementation_snapshot(
    impl_root: Path,
    manifest_path: Path,
    archive_path: Path,
) -> ImplementationSnapshot:
    if manifest_path.exists() or archive_path.exists():
        manifest = pin_json(manifest_path)
        archive = pin_file(archive_path)
    else:
        capture_worktree(impl_root, archive_path, manifest_path, "implementation")
        manifest = pin_json(manifest_path)
        archive = pin_file(archive_path)
    verify_implementation_snapshot(manifest, archive, implementation_sha(impl_root))
    verify_implementation_git_state(impl_root, manifest)
    return ImplementationSnapshot(
        manifest=manifest,
        archive=archive,
        sha256=manifest_implementation_sha(manifest),
        git_state_sha256=manifest_implementation_git_sha(manifest),
    )

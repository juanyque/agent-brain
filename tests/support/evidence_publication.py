from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from evidence_json import (
    BytesOutput,
    ContractError,
    _CREATE_FLAGS,
    _DIRECTORY_FLAGS,
    _FileIdentity,
    _OutputSpec,
    _PinnedOutput,
    _fstat_identity,
    _parse_output_path,
    _prepare_pair_outputs,
    _quarantine_name,
    _require_absent_leaf,
    _rollback_created_output,
    _write_all,
)


@dataclass(frozen=True, slots=True)
class StatePublication:
    output: Path
    sidecar_dir: Path
    sidecars: tuple[BytesOutput, ...]
    manifest: bytes


@dataclass(frozen=True, slots=True)
class _CreatedFile:
    output: _PinnedOutput
    identity: _FileIdentity


@dataclass(frozen=True, slots=True)
class _DirectoryPublication:
    output: _PinnedOutput
    descriptor: int
    identity: _FileIdentity


def publish_state_capture(publication: StatePublication) -> None:
    """Create outputs with ordinary rollback under a cooperative evidence parent.

    A same-user process must not rename, unlink, or replace entries there while this runs.
    """
    directory_spec = _parse_output_path(publication.sidecar_dir)
    final_spec = _parse_output_path(publication.output)
    directory_output, final_output = _prepare_pair_outputs(directory_spec, final_spec)
    close_outputs: tuple[_PinnedOutput, ...] = (directory_output, final_output)
    directory: _DirectoryPublication | None = None
    created_files: list[_CreatedFile] = []
    primary: ContractError | None = None
    try:
        directory = _create_sidecar_directory(directory_output)
        for path, data in publication.sidecars:
            sidecar_output = _sidecar_output(directory, directory_spec, path)
            identity = _create_owned_file(sidecar_output, data, 0o600)
            created_files.append(_CreatedFile(sidecar_output, identity))
        manifest_identity = _create_owned_file(final_output, publication.manifest, 0o600)
        created_files.append(_CreatedFile(final_output, manifest_identity))
    except (ContractError, OSError) as error:
        primary = _contract_error(error, publication.output)
        cleanup_error = _rollback_publication(created_files, directory)
        if cleanup_error is not None:
            primary = ContractError(f"{primary}; cleanup incomplete: {cleanup_error}")
    close_error = _close_publication(directory, close_outputs)
    if primary is not None:
        raise primary
    if close_error is not None:
        raise close_error


def _create_sidecar_directory(output: _PinnedOutput) -> _DirectoryPublication:
    try:
        os.mkdir(output.leaf, 0o700, dir_fd=output.parent_fd)
    except OSError as error:
        raise ContractError(f"create-only destination rejected: {output.path}") from error
    descriptor = -1
    try:
        descriptor = os.open(
            output.leaf,
            _DIRECTORY_FLAGS | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=output.parent_fd,
        )
        identity = _fstat_identity(descriptor, output.path)
        return _DirectoryPublication(output, descriptor, identity)
    except (ContractError, OSError) as error:
        if descriptor >= 0:
            _close_descriptor(descriptor, output.path)
        _rollback_unidentified_directory(output)
        raise ContractError(f"create-only destination rejected: {output.path}") from error


def _sidecar_output(
    directory: _DirectoryPublication, directory_spec: _OutputSpec, path: Path
) -> _PinnedOutput:
    spec = _parse_output_path(path)
    if spec.parent_parts != directory_spec.parent_parts + (directory_spec.leaf,):
        raise ContractError(f"sidecar path escapes sidecar directory: {path}")
    _require_absent_leaf(directory.descriptor, spec.leaf, spec.path)
    return _PinnedOutput(spec.path, directory.descriptor, spec.leaf)


def _create_owned_file(output: _PinnedOutput, data: bytes, mode: int) -> _FileIdentity:
    try:
        descriptor = os.open(output.leaf, _CREATE_FLAGS, mode, dir_fd=output.parent_fd)
    except OSError as error:
        raise ContractError(f"create-only destination rejected: {output.path}") from error
    identity: _FileIdentity | None = None
    primary: ContractError | None = None
    try:
        identity = _fstat_identity(descriptor, output.path)
        _write_all(descriptor, data)
        os.fsync(descriptor)
    except (ContractError, OSError) as error:
        primary = _contract_error(error, output.path)
    close_error = _close_descriptor(descriptor, output.path)
    if primary is not None:
        _rollback_known_or_unverified_file(output, identity)
        raise primary
    if close_error is not None:
        _rollback_known_or_unverified_file(output, identity)
        raise close_error
    if identity is None:
        raise ContractError(f"created output identity unavailable: {output.path}")
    return identity


def _rollback_publication(
    created_files: list[_CreatedFile],
    directory: _DirectoryPublication | None,
) -> ContractError | None:
    cleanup_error: ContractError | None = None
    for created in reversed(created_files):
        try:
            _rollback_created_output(created.output, created.identity)
        except ContractError as error:
            cleanup_error = cleanup_error or error
    if directory is not None:
        try:
            _rollback_created_directory(directory)
        except ContractError as error:
            cleanup_error = cleanup_error or error
    return cleanup_error


def _rollback_unidentified_directory(output: _PinnedOutput) -> None:
    try:
        os.rmdir(output.leaf, dir_fd=output.parent_fd)
    except FileNotFoundError:
        return
    except OSError as error:
        raise ContractError(f"directory rollback failed for {output.path}") from error


def _rollback_created_directory(directory: _DirectoryPublication) -> None:
    quarantine = _rename_directory_to_quarantine(directory.output)
    if quarantine is None:
        return
    descriptor = os.open(
        quarantine,
        _DIRECTORY_FLAGS | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory.output.parent_fd,
    )
    try:
        quarantined_identity = _fstat_identity(descriptor, directory.output.path)
    finally:
        _close_descriptor(descriptor, directory.output.path)
    if quarantined_identity == directory.identity:
        try:
            os.rmdir(quarantine, dir_fd=directory.output.parent_fd)
        except OSError as error:
            raise ContractError(
                f"directory rollback cleanup failed for {directory.output.path}: "
                f"preserved quarantine {quarantine}"
            ) from error
        return
    _restore_directory_quarantine(directory.output, quarantine)


def _rename_directory_to_quarantine(output: _PinnedOutput) -> str | None:
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
            raise ContractError(f"directory rollback quarantine failed for {output.path}") from error
    raise ContractError(f"directory rollback quarantine name collision for {output.path}")


def _restore_directory_quarantine(output: _PinnedOutput, quarantine: str) -> None:
    try:
        _require_absent_leaf(output.parent_fd, output.leaf, output.path)
        os.rename(
            quarantine,
            output.leaf,
            src_dir_fd=output.parent_fd,
            dst_dir_fd=output.parent_fd,
        )
    except ContractError as error:
        raise ContractError(
            f"directory rollback restoration conflict for {output.path}: "
            f"preserved quarantine {quarantine}"
        ) from error
    except OSError as error:
        raise ContractError(
            f"directory rollback restoration failed for {output.path}: "
            f"preserved quarantine {quarantine}"
        ) from error


def _rollback_known_or_unverified_file(
    output: _PinnedOutput, identity: _FileIdentity | None
) -> None:
    if identity is None:
        _rollback_unidentified_file(output)
        return
    _rollback_created_output(output, identity)


def _rollback_unidentified_file(output: _PinnedOutput) -> None:
    try:
        os.unlink(output.leaf, dir_fd=output.parent_fd)
    except FileNotFoundError:
        return
    except OSError as error:
        raise ContractError(f"file rollback failed for {output.path}") from error


def _close_publication(
    directory: _DirectoryPublication | None, outputs: tuple[_PinnedOutput, ...]
) -> ContractError | None:
    result: ContractError | None = None
    if directory is not None:
        result = _close_descriptor(directory.descriptor, directory.output.path)
    for output in outputs:
        close_error = _close_descriptor(output.parent_fd, output.path)
        result = result or close_error
    return result


def _close_descriptor(descriptor: int, path: Path) -> ContractError | None:
    try:
        os.close(descriptor)
    except OSError as error:
        return ContractError(f"descriptor close failed: {path}: {error}")
    return None


def _contract_error(error: ContractError | OSError, path: Path) -> ContractError:
    match error:
        case ContractError():
            return error
        case OSError():
            return ContractError(f"create-only destination rejected: {path}")
        case unreachable:
            assert_never(unreachable)

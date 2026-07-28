from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator

DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)


class UnsafeDailyPathError(OSError):
    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"unsafe daily path: {path}")


class SafeWriteContextError(RuntimeError):
    pass


_ACTIVE_SAFE_ROOT: ContextVar[Path | None] = ContextVar("session_open_safe_root", default=None)


def _open_parent_no_follow(path: Path, safe_root: Path) -> tuple[int, str]:
    parts = path.relative_to(safe_root).parts
    if not parts:
        raise OSError(f"refusing safe-root path as a file: {path}")
    descriptor = os.open(
        safe_root,
        DIRECTORY_FLAGS | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError(f"refusing non-directory safe root: {safe_root}")
        for part in parts[:-1]:
            next_descriptor = os.open(
                part,
                DIRECTORY_FLAGS | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            if not stat.S_ISDIR(os.fstat(next_descriptor).st_mode):
                os.close(next_descriptor)
                raise OSError(f"refusing non-directory path component: {path}")
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, parts[-1]
    except OSError:
        os.close(descriptor)
        raise


def _open_regular_no_follow(
    path: Path,
    flags: int,
    safe_root: Path | None = None,
) -> int:
    if safe_root is None:
        descriptor = os.open(path.parent, DIRECTORY_FLAGS)
        name = path.name
    else:
        descriptor, name = _open_parent_no_follow(path, safe_root)
    try:
        file_descriptor = os.open(
            name,
            flags | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=descriptor,
        )
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            os.close(file_descriptor)
            raise OSError(f"refusing non-regular file: {path}")
        return file_descriptor
    finally:
        os.close(descriptor)


def _read_daily_text(path: Path, safe_root: Path) -> str:
    try:
        descriptor = _open_regular_no_follow(path, os.O_RDONLY, safe_root)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            return stream.read()
    except (OSError, ValueError) as exc:
        raise UnsafeDailyPathError(path) from exc


def _read_optional_daily_text(path: Path, safe_root: Path) -> str | None:
    try:
        descriptor = _open_regular_no_follow(path, os.O_RDONLY, safe_root)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise UnsafeDailyPathError(path) from exc
    with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
        return stream.read()


def _unlink_daily_no_follow(path: Path, safe_root: Path) -> None:
    try:
        descriptor, name = _open_parent_no_follow(path, safe_root)
        try:
            mode = os.stat(name, dir_fd=descriptor, follow_symlinks=False).st_mode
            if not stat.S_ISREG(mode):
                raise OSError(f"refusing non-regular file: {path}")
            os.unlink(name, dir_fd=descriptor)
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as exc:
        raise UnsafeDailyPathError(path) from exc


@contextmanager
def _safe_write_scope(safe_root: Path) -> Iterator[None]:
    token = _ACTIVE_SAFE_ROOT.set(safe_root)
    try:
        yield
    finally:
        _ACTIVE_SAFE_ROOT.reset(token)


def _restore_regular_file_no_follow(
    path: Path,
    content: bytes,
    safe_root: Path,
) -> str | None:
    try:
        descriptor = _open_regular_no_follow(path, os.O_WRONLY, safe_root)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.truncate()
    except OSError as exc:
        return f"{path}: {exc}"
    return None


def _write_text(path: Path, content: str) -> None:
    safe_root = _ACTIVE_SAFE_ROOT.get()
    if safe_root is None:
        raise SafeWriteContextError("safe-root write context is not active")
    try:
        try:
            descriptor = _open_regular_no_follow(
                path,
                os.O_WRONLY | os.O_TRUNC,
                safe_root,
            )
        except FileNotFoundError:
            parent_descriptor, name = _open_parent_no_follow(path, safe_root)
            try:
                descriptor = os.open(
                    name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o666,
                    dir_fd=parent_descriptor,
                )
            finally:
                os.close(parent_descriptor)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                raise OSError(f"refusing non-regular file: {path}")
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
    except (OSError, ValueError) as exc:
        raise UnsafeDailyPathError(path) from exc


def _create_session_note_no_follow(
    brain_root: Path,
    note_path: Path,
    content: str,
) -> list[Path]:
    relative = note_path.relative_to(brain_root)
    descriptors = [
        os.open(
            brain_root,
            DIRECTORY_FLAGS | getattr(os, "O_NOFOLLOW", 0),
        )
    ]
    created_parents: list[Path] = []
    note_created = False
    current = brain_root
    try:
        for part in relative.parent.parts:
            current = current / part
            try:
                os.mkdir(part, dir_fd=descriptors[-1])
            except FileExistsError:
                created = False
            else:
                created = True
            if created:
                created_parents.append(current)
            descriptors.append(
                os.open(
                    part,
                    DIRECTORY_FLAGS | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptors[-1],
                )
            )
        note_descriptor = os.open(
            relative.name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o666,
            dir_fd=descriptors[-1],
        )
        note_created = True
        with os.fdopen(note_descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
    except OSError:
        if note_created:
            os.unlink(relative.name, dir_fd=descriptors[-1])
        for parent in reversed(created_parents):
            parts = parent.relative_to(brain_root).parts
            os.rmdir(parts[-1], dir_fd=descriptors[len(parts) - 1])
        raise
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    return created_parents


def _rollback_created_session_note(
    brain_root: Path,
    note_path: Path,
    created_parents: list[Path],
) -> list[str]:
    errors: list[str] = []
    relative = note_path.relative_to(brain_root)
    descriptors: list[int] = []
    try:
        descriptors.append(
            os.open(
                brain_root,
                DIRECTORY_FLAGS | getattr(os, "O_NOFOLLOW", 0),
            )
        )
        for part in relative.parent.parts:
            descriptors.append(
                os.open(
                    part,
                    DIRECTORY_FLAGS | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptors[-1],
                )
            )
    except OSError as exc:
        errors.append(f"{note_path}: {exc}")
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        return errors
    try:
        try:
            os.unlink(relative.name, dir_fd=descriptors[-1])
        except FileNotFoundError:
            pass
        except OSError as exc:
            errors.append(f"{note_path}: {exc}")
        for parent in reversed(created_parents):
            parts = parent.relative_to(brain_root).parts
            try:
                os.rmdir(parts[-1], dir_fd=descriptors[len(parts) - 1])
            except OSError as exc:
                errors.append(f"{parent}: {exc}")
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    return errors

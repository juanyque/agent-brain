from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import override

from selection_inputs import SelectionProjectError


class OutputState(StrEnum):
    COMMITTED = "committed"
    IGNORED = "ignored"
    MODIFIED = "modified"
    UNTRACKED = "untracked"
    UNVERSIONED = "unversioned"


@dataclass(frozen=True, slots=True)
class ExistingOutput:
    path: Path
    state: OutputState


@dataclass(frozen=True, slots=True)
class OutputExistsError(SelectionProjectError):
    output: ExistingOutput

    @override
    def __str__(self) -> str:
        return (
            f"output already exists ({self.output.state.value}): "
            f"{self.output.path}; rerun with --replace only after confirmation"
        )


@dataclass(frozen=True, slots=True)
class OutboxLocationError(SelectionProjectError):
    path: Path
    outbox: Path

    @override
    def __str__(self) -> str:
        return f"printable brain output must be inside {self.outbox}: {self.path}"


@dataclass(frozen=True, slots=True)
class IgnoredOutboxError(SelectionProjectError):
    path: Path

    @override
    def __str__(self) -> str:
        return f"OUTBOX output is ignored by Git and would be invisible: {self.path}"


def _git(
    cwd: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def _repository_root(cwd: Path) -> Path | None:
    result = _git(cwd, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def output_state(path: Path, repository_hint: Path) -> OutputState:
    repository = _repository_root(repository_hint)
    if repository is None:
        return OutputState.UNVERSIONED
    resolved = path.resolve(strict=False)
    try:
        relative = resolved.relative_to(repository)
    except ValueError:
        return OutputState.UNVERSIONED
    pathspec = relative.as_posix()
    ignored = _git(
        repository,
        "check-ignore",
        "--quiet",
        "--no-index",
        "--",
        pathspec,
    )
    if ignored.returncode == 0:
        return OutputState.IGNORED
    status = _git(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        pathspec,
    )
    if status.stdout.startswith("??"):
        return OutputState.UNTRACKED
    if status.stdout:
        return OutputState.MODIFIED
    tracked = _git(repository, "ls-files", "--error-unmatch", "--", pathspec)
    if tracked.returncode == 0:
        return OutputState.COMMITTED
    return OutputState.UNVERSIONED


def require_visible_outbox(path: Path, brain_root: Path) -> None:
    outbox = brain_root.resolve() / "OUTBOX"
    resolved = path.resolve(strict=False)
    try:
        _ = resolved.relative_to(outbox)
    except ValueError as error:
        raise OutboxLocationError(path=resolved, outbox=outbox) from error
    if output_state(resolved, brain_root) is OutputState.IGNORED:
        raise IgnoredOutboxError(path=resolved)


def existing_output(
    paths: tuple[Path, ...],
    repository_hint: Path,
) -> ExistingOutput | None:
    for path in paths:
        if path.exists():
            return ExistingOutput(
                path=path,
                state=output_state(path, repository_hint),
            )
    return None

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import assert_never, override

from selection_inputs import SelectionProjectError
from workspace_config import GitVisibility, ResolvedWorkspace


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
class DeliverableLocationError(SelectionProjectError):
    path: Path
    deliverables_root: Path

    @override
    def __str__(self) -> str:
        return f"printable output must be inside {self.deliverables_root}: {self.path}"


@dataclass(frozen=True, slots=True)
class IgnoredDeliverableError(SelectionProjectError):
    path: Path

    @override
    def __str__(self) -> str:
        return f"deliverable is ignored by Git and would be invisible: {self.path}"


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


def require_deliverable(path: Path, workspace: ResolvedWorkspace) -> None:
    resolved = path.resolve(strict=False)
    try:
        _ = resolved.relative_to(workspace.deliverables_root)
    except ValueError as error:
        raise DeliverableLocationError(
            path=resolved,
            deliverables_root=workspace.deliverables_root,
        ) from error
    match workspace.policies.deliverables_git_visibility:
        case GitVisibility.REQUIRED:
            if output_state(resolved, workspace.workspace_root) is OutputState.IGNORED:
                raise IgnoredDeliverableError(path=resolved)
        case GitVisibility.UNRESTRICTED:
            return
        case unreachable:
            assert_never(unreachable)


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

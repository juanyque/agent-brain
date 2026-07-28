from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias


REPO_LINKS: Final = (
    ".git",
    "bootstrap-zero.sh",
    "docs",
    "examples",
    "model",
    "README.md",
    "skills",
)
TEST_LINKS: Final = ("fixtures", "support")
UNSAFE_ID_CHARS: Final = frozenset({"/", "\\", ":", "\x00", "\u2044", "\u2215"})
JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclass(frozen=True, slots=True)
class BaselineError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class BaselineModuleRef:
    import_name: str
    relative_path: Path


@dataclass(frozen=True, slots=True)
class MaterializedModule:
    import_name: str
    relative_path: Path
    materialized_path: Path
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class BaselineRunResult:
    status: int
    loaded_ids: list[str]
    transcript: str
    provenance: dict[str, JsonValue]


def module_refs_from_ids(ids: list[str]) -> list[BaselineModuleRef]:
    refs: dict[Path, BaselineModuleRef] = {}
    for identifier in ids:
        import_name, relative = _import_and_path(identifier)
        refs.setdefault(relative, BaselineModuleRef(import_name, relative))
    return [refs[path] for path in sorted(refs)]


def _import_and_path(identifier: str) -> tuple[str, Path]:
    parts = identifier.split(".")
    if (
        any(char in identifier for char in UNSAFE_ID_CHARS)
        or any(part == "" for part in parts)
    ):
        raise BaselineError(f"invalid baseline test ID: {identifier}")
    if parts[0] == "tests":
        canonical = parts
        import_name = ".".join(parts[:-2])
    elif parts[0].startswith("test_"):
        canonical = ["tests", *parts]
        import_name = ".".join(parts[:-2])
    else:
        raise BaselineError(f"invalid baseline test ID: {identifier}")
    if len(canonical) < 4 or not all(part.isidentifier() for part in canonical):
        raise BaselineError(f"invalid baseline test ID: {identifier}")
    module_parts = canonical[1:-2]
    if not module_parts or not module_parts[0].startswith("test_"):
        raise BaselineError(f"invalid baseline test ID: {identifier}")
    return import_name, Path("tests", *module_parts).with_suffix(".py")


def read_git_object(root: Path, git_ref: str, relative_path: Path) -> bytes:
    try:
        result = subprocess.run(
            ["git", "show", f"{git_ref}:{relative_path.as_posix()}"],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise BaselineError(f"baseline git read failed: {relative_path}") from error
    if result.returncode != 0:
        raise BaselineError(f"baseline test missing at ref: {relative_path}")
    return result.stdout


def materialize_baseline_modules(
    root: Path,
    git_ref: str,
    refs: list[BaselineModuleRef],
    temp_root: Path,
) -> list[MaterializedModule]:
    _link_repo_shape(root, temp_root)
    modules: list[MaterializedModule] = []
    for ref in refs:
        expected = read_git_object(root, git_ref, ref.relative_path)
        destination = temp_root / ref.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(expected)
        verify_materialized_bytes(ref, expected, destination)
        modules.append(
            MaterializedModule(
                import_name=ref.import_name,
                relative_path=ref.relative_path,
                materialized_path=destination,
                sha256=hashlib.sha256(expected).hexdigest(),
                size=len(expected),
            )
        )
    return modules


def verify_materialized_bytes(
    ref: BaselineModuleRef,
    expected: bytes,
    materialized_path: Path,
) -> None:
    if materialized_path.read_bytes() != expected:
        raise BaselineError(f"materialized baseline test corrupted: {ref.relative_path}")


def run_materialized_ids(
    root: Path,
    temp_root: Path,
    modules: list[MaterializedModule],
    ids: list[str],
) -> BaselineRunResult:
    request = temp_root / "baseline-request.json"
    request.write_text(
        json.dumps(
            {"ids": ids, "root": os.fspath(root), "temp_root": os.fspath(temp_root)},
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE"):
        env.pop(name, None)
    child = Path(__file__).with_name("baseline_child.py")
    result = subprocess.run(
        [sys.executable, "-B", "-I", os.fspath(child), "--request", os.fspath(request)],
        cwd=temp_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if not result.stdout:
        raise BaselineError(f"baseline child failed: {result.stderr.strip()}")
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise BaselineError("baseline child emitted invalid JSON") from error
    if int(report["status"]) == 2:
        raise BaselineError(str(report["error"]))
    return BaselineRunResult(
        status=int(report["status"]),
        loaded_ids=[str(identifier) for identifier in report["loaded_ids"]],
        transcript=str(report["transcript"]),
        provenance=dict(report["provenance"]),
    )


def _link_repo_shape(root: Path, temp_root: Path) -> None:
    tests_dir = temp_root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    for name in REPO_LINKS:
        _symlink_if_present(root / name, temp_root / name)
    for name in TEST_LINKS:
        _symlink_if_present(root / "tests" / name, tests_dir / name)


def _symlink_if_present(source: Path, destination: Path) -> None:
    if not source.exists() or destination.exists():
        return
    destination.symlink_to(source, target_is_directory=source.is_dir())

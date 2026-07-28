from __future__ import annotations

import fnmatch
import json
import subprocess
from pathlib import Path

from model_check_contract import CodeDef, Finding


def _status_paths(raw: bytes) -> tuple[str, ...]:
    entries = raw.decode("utf-8", errors="replace").split("\0")
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        if entry[:2] in {"R ", "C "} and index < len(entries):
            paths.append(entries[index])
            index += 1
            continue
        paths.append(entry[3:] if len(entry) > 3 else entry)
    return tuple(path for path in paths if path)


def _implementation_status_paths(raw: bytes) -> tuple[str, ...]:
    return tuple(path for path in _status_paths(raw) if not path.startswith(".omo/"))


def _nul_paths(raw: bytes) -> tuple[str, ...]:
    return tuple(path for path in raw.decode("utf-8", errors="replace").split("\0") if path)


def _scope_rows(root: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        raw = json.loads((root / "model" / "OPERATING-MODEL.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (("*",), ())
    scope = raw.get("scope", {})
    if not isinstance(scope, dict):
        return (("*",), ())
    allow = tuple(item for item in scope.get("allow", []) if isinstance(item, str))
    deny = tuple(item for item in scope.get("deny", []) if isinstance(item, str))
    return (allow or ("*",), deny)


def _matches(patterns: tuple[str, ...], path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _out_of_scope_paths(root: Path, paths: tuple[str, ...]) -> tuple[str, ...]:
    allow, deny = _scope_rows(root)
    return tuple(
        path
        for path in sorted(set(paths))
        if _matches(deny, path) or not _matches(allow, path)
    )


def _untracked_paths(root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return ()
    return _nul_paths(result.stdout)


def _untracked_whitespace_errors(root: Path) -> tuple[str, ...]:
    errors: list[str] = []
    for rel_path in _untracked_paths(root):
        path = root / rel_path
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            stripped = line.rstrip("\n\r")
            if stripped.rstrip(" \t") != stripped:
                errors.append(f"{rel_path}:{line_number}: trailing whitespace.")
    return tuple(errors)


def worktree_findings(root: Path, code: CodeDef) -> list[Finding]:
    match code.check:
        case "worktree-nul-status":
            return _worktree_status_findings(root, code)
        case "whitespace-diff-check":
            return _worktree_whitespace_findings(root, code)
        case _:
            return []


def _worktree_status_findings(root: Path, code: CodeDef) -> list[Finding]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "-uall"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return [
            Finding(
                code.code,
                code.family,
                code.severity,
                ".",
                "git status --porcelain=v1 -z -uall",
                result.stderr.decode(errors="replace").strip(),
            )
        ]
    paths = _implementation_status_paths(result.stdout)
    if code.code != "out-of-scope-path":
        return []
    return [
        Finding(
            code.code,
            code.family,
            code.severity,
            path,
            "scope.allow",
            "worktree path is outside the governed implementation scope",
        )
        for path in _out_of_scope_paths(root, paths)
    ]


def _worktree_whitespace_findings(root: Path, code: CodeDef) -> list[Finding]:
    result = subprocess.run(
        ["git", "diff", "HEAD", "--check"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    untracked_errors = _untracked_whitespace_errors(root)
    if result.returncode == 0 and not untracked_errors:
        return []
    message = "\n".join(
        item
        for item in (result.stdout.strip(), "\n".join(untracked_errors))
        if item
    )
    return [
        Finding(
            code.code,
            code.family,
            code.severity,
            ".",
            "git diff HEAD --check",
            message or "whitespace errors detected",
        )
    ]


def committed_findings(root: Path, git_base: str, code: CodeDef) -> list[Finding]:
    if code.check != "committed-ref-head":
        return []
    result = subprocess.run(
        ["git", "diff", "--name-only", "-z", f"{git_base}...HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return [
            Finding(
                code.code,
                code.family,
                code.severity,
                ".",
                f"{git_base}...HEAD",
                result.stderr.decode(errors="replace").strip(),
            )
        ]
    return [
        Finding(
            code.code,
            code.family,
            code.severity,
            path,
            f"{git_base}...HEAD",
            "committed path is outside the governed implementation scope",
        )
        for path in _out_of_scope_paths(root, _nul_paths(result.stdout))
    ]

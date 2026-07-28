from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from model_check_contract import CodeDef, Finding


GIT_MUTATION_RE = re.compile(
    r"\bgit\s+(?:add|am|apply|bisect|branch|checkout|cherry-pick|clean|commit|merge|mv|"
    r"pull|push|rebase|reset|restore|revert|rm|stash|switch|tag|worktree)\b"
)
AUTHORIZATION_RE = re.compile(
    r"(?:explicit (?:user|human) (?:approval|authorization|confirmation|request|decision))|"
    r"(?:user-authorized)|(?:explicitly (?:approved|authorized|requested|confirmed|decides?))|"
    r"(?:only with explicit)|(?:wait for explicit human approval)",
    re.IGNORECASE,
)
GIT_AUTHORIZATION_RE = re.compile(
    r"(?:Git (?:operations?|actions?|commands?|workflow decisions?).{0,100}(?:explicit|user-authorized))|"
    r"(?:(?:explicit|user-authorized).{0,100}Git (?:operation|action|command|authorization))",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class GitAuthority:
    git_mv_condition: str
    repository_state_mutation: str


def git_authority(common_path: Path) -> GitAuthority:
    return git_authority_from_text(common_path.read_text(encoding="utf-8"))


def git_authority_from_text(text: str) -> GitAuthority:
    git_condition = (
        "explicit-git-authorization"
        if "Git operations require explicit user authorization." in text
        else "missing-explicit-git-authorization"
    )
    mutation = "user-owned" if "Git repository state is user-owned." in text else "undeclared"
    return GitAuthority(git_mv_condition=git_condition, repository_state_mutation=mutation)


def _model_markdown_paths(root: Path) -> tuple[Path, ...]:
    model = root / "model"
    if not model.exists():
        return ()
    return tuple(
        sorted(
            path
            for path in model.rglob("*.common.md")
            if path.is_file()
        )
    )


def _context_for_line(lines: list[str], index: int) -> str:
    start = index
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = index + 1
    while end < len(lines) and lines[end].strip():
        end += 1
    return "\n".join(lines[start:end])


def _git_authorized(line: str, context: str) -> bool:
    git_match = GIT_MUTATION_RE.search(line)
    auth_match = AUTHORIZATION_RE.search(line)
    if (
        git_match is not None
        and auth_match is not None
        and (
            auth_match.start() < git_match.start()
            or GIT_AUTHORIZATION_RE.search(line) is not None
        )
    ):
        return True
    return GIT_AUTHORIZATION_RE.search(context) is not None


def git_command_guard_findings(root: Path, code: CodeDef) -> list[Finding]:
    findings: list[Finding] = []
    for path in _model_markdown_paths(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        rel_path = path.relative_to(root).as_posix()
        for line_number, line in enumerate(lines, start=1):
            if GIT_MUTATION_RE.search(line) is None:
                continue
            context = _context_for_line(lines, line_number - 1)
            if _git_authorized(line, context):
                continue
            findings.append(
                Finding(
                    code=code.code,
                    family=code.family,
                    severity=code.severity,
                    path=rel_path,
                    target=f"line:{line_number}",
                    message="Git-mutating command is not conditional on explicit user authorization",
                )
            )
    return sorted(findings, key=lambda item: (item.path, item.target, item.message))

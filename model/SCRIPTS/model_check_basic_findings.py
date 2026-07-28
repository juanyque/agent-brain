from __future__ import annotations

from pathlib import Path

from brain_state import link_status
from model_check_contract import CodeDef, Finding, JsonValue
from model_check_git_authority import git_authority, git_command_guard_findings
from model_check_git_scope import committed_findings, worktree_findings


def brain_findings(code: CodeDef, brain_root: Path, common_root: Path) -> list[Finding]:
    status, desired = link_status(brain_root, common_root)
    path = str(brain_root / "_COMMON")
    status_codes = {
        "missing": "common-link-missing",
        "conflict-not-symlink": "common-link-not-symlink",
        "conflict-invalid-target": "common-link-broken",
        "conflict-wrong-target": "common-link-wrong-target",
    }
    if status_codes.get(status) != code.code:
        return []
    match status:
        case "ok":
            return []
        case "missing":
            return [
                Finding(code.code, code.family, "warning", path, desired, "_COMMON is missing for an attached brain")
            ]
        case "conflict-not-symlink":
            return [
                Finding(code.code, code.family, "error", path, desired, "_COMMON exists but is not a symlink")
            ]
        case "conflict-invalid-target":
            return [
                Finding(code.code, code.family, "error", path, desired, "_COMMON symlink target is missing")
            ]
        case "conflict-wrong-target":
            return [
                Finding(code.code, code.family, "error", path, desired, "_COMMON points at a different model")
            ]
        case _:
            return []

def audience_findings(model: dict[str, JsonValue], code: CodeDef) -> list[Finding]:
    governed = model.get("governed_inventory", [])
    audience = model.get("audience_contract", [])
    if not isinstance(governed, list) or not isinstance(audience, list):
        return [
            Finding(
                code.code,
                code.family,
                code.severity,
                "model/OPERATING-MODEL.json",
                "audience_contract",
                "governed inventory audience contract is malformed",
            )
        ]
    governed_paths = {item for item in governed if isinstance(item, str)}
    audience_by_path = {
        row["path"]: row
        for row in audience
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }
    findings = [
        Finding(code.code, code.family, code.severity, path, "audience_contract", "governed path has no declared audience")
        for path in sorted(governed_paths - set(audience_by_path))
    ]
    root_agents = audience_by_path.get("AGENTS.md")
    if (
        root_agents is None
        or root_agents.get("audience") != "maintainer-only"
        or root_agents.get("brain_session_context") != "excluded"
    ):
        findings.append(
            Finding(
                code.code,
                code.family,
                code.severity,
                "AGENTS.md",
                "maintainer-only excluded",
                "root AGENTS.md must be excluded from brain session context",
            )
        )
    return findings


def git_authority_findings(root: Path, code: CodeDef) -> list[Finding]:
    findings = git_command_guard_findings(root, code)
    authority = git_authority(root / "model" / "AGENTS.common.md")
    if (
        authority.git_mv_condition == "brain-internal-standing-authorization"
        and authority.other_git_condition == "explicit-git-authorization"
        and authority.repository_state_mutation == "user-owned"
    ):
        return findings
    findings.append(
        Finding(
            code=code.code,
            family=code.family,
            severity=code.severity,
            path="model/AGENTS.common.md",
            target="bounded-git-mv-authorization explicit-other-git-authorization user-owned",
            message="common model Git authority is incomplete or over-broad",
        )
    )
    return findings

from __future__ import annotations

from pathlib import Path

from model_check_basic_findings import (
    audience_findings,
    brain_findings,
    committed_findings,
    git_authority_findings,
    worktree_findings,
)
from model_check_contract import CodeDef, Finding, JsonValue
from model_check_policy_findings import policy_owner_findings
from model_check_routes import orphan_rule_findings, route_target_findings


def _matching(findings: list[Finding], code: CodeDef) -> list[Finding]:
    return [finding for finding in findings if finding.code == code.code]


def _duplicate_policy_findings(root: Path, model: dict[str, JsonValue], code: CodeDef) -> list[Finding]:
    from model_check_content_boundaries import content_boundary_findings
    from model_check_evidence_ownership import scan_evidence_ownership

    findings = policy_owner_findings(root, model, code)
    findings.extend(_matching(scan_evidence_ownership(root), code))
    findings.extend(_matching(content_boundary_findings(root), code))
    return findings


def _default_findings(
    root: Path,
    model: dict[str, JsonValue],
    code: CodeDef,
) -> list[Finding]:
    if code.code == "uncovered-audience":
        return audience_findings(model, code)
    if code.code == "duplicate-policy-owner":
        return _duplicate_policy_findings(root, model, code)
    if code.code == "misplaced-policy-owner":
        return policy_owner_findings(root, model, code)
    if code.code in {
        "duplicate-route-id",
        "malformed-route-metadata",
        "missing-route-target",
        "unmapped-cluster",
    }:
        return _matching(route_target_findings(root, model, root / "model" / "AGENTS.common.md"), code)
    if code.code == "orphan-model-artifact":
        return orphan_rule_findings(root, model, root / "model" / "AGENTS.common.md")
    if code.code == "missing-task-target":
        from model_check_content_boundaries import content_boundary_findings

        return _matching(content_boundary_findings(root), code)
    if code.code in {"missing-skill-reference", "unreachable-conditional-artifact"}:
        from model_check_skill_dependencies import skill_dependency_findings

        return skill_dependency_findings(root, model, code)
    if code.family == "session-ownership":
        from model_check_session_ownership import session_ownership_findings

        return _matching(session_ownership_findings(root), code)
    if code.family in {"evidence-ownership", "review-status"}:
        from model_check_evidence_ownership import scan_evidence_ownership

        return _matching(scan_evidence_ownership(root), code)
    if code.family == "content-boundary":
        from model_check_content_boundaries import content_boundary_findings

        return _matching(content_boundary_findings(root), code)
    if code.check == "git-authority-explicit":
        return git_authority_findings(root, code)
    return []


def code_findings(
    root: Path,
    model: dict[str, JsonValue],
    model_path: Path,
    code: CodeDef,
    brain_root: Path | None,
    git_base: str | None,
) -> list[Finding]:
    match code.selection:
        case "brain":
            if brain_root is None:
                return []
            if code.check == "brain-common-link":
                return brain_findings(code, brain_root, root / "model")
            if code.check == "brain-compatibility":
                from model_check_brain_compat import scan_brain_compatibility

                return _matching(scan_brain_compatibility(brain_root, root / "model", model_path), code)
            return []
        case "worktree":
            return worktree_findings(root, code)
        case "committed":
            if git_base is None:
                return []
            return committed_findings(root, git_base, code)
        case "default":
            return _default_findings(root, model, code)
        case _:
            return []

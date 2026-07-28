from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from model_check_contract import Finding, JsonValue


BOUNDARY_PATTERN = re.compile(r"<!--\s*content-boundary:\s*(\{.*?\})\s*-->")
TASK_LINK_PATTERN = re.compile(r"^\s*-\s*\[\[([^]|#]+)")


@dataclass(frozen=True, slots=True)
class TaskTypeTarget:
    source: Path
    path: Path
    link: str


@dataclass(frozen=True, slots=True)
class BoundaryClaim:
    path: str
    kind: str
    policy_id: str
    owner: str
    capability: str
    startup: str


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _task_target(root: Path, raw_link: str) -> Path:
    stem = raw_link.removesuffix(".md").removesuffix(".common")
    if "/" in stem:
        return root / "model" / "TASK_TYPES" / f"{Path(stem).name}.common.md"
    return root / "model" / "TASK_TYPES" / f"{stem}.common.md"


def task_type_index_targets(root: Path) -> tuple[TaskTypeTarget, ...]:
    index = root / "model" / "TASK_TYPES" / "TASK_TYPES.common.md"
    if not index.exists():
        return ()
    targets: list[TaskTypeTarget] = []
    for line in index.read_text(encoding="utf-8").splitlines():
        match = TASK_LINK_PATTERN.match(line)
        if match is None:
            continue
        raw_link = match.group(1).strip()
        targets.append(
            TaskTypeTarget(
                source=index,
                path=_task_target(root, raw_link),
                link=raw_link,
            )
        )
    return tuple(targets)


def _metadata_value(raw: JsonValue, key: str) -> str:
    if isinstance(raw, dict):
        value = raw.get(key)
        if isinstance(value, str):
            return value
    return ""


def _boundary_claims(root: Path) -> tuple[BoundaryClaim, ...]:
    claims: list[BoundaryClaim] = []
    for path in sorted((root / "model").rglob("*.common.md")):
        rel = _relative(root, path)
        for match in BOUNDARY_PATTERN.finditer(path.read_text(encoding="utf-8")):
            try:
                raw = json.loads(match.group(1))
            except json.JSONDecodeError:
                claims.append(
                    BoundaryClaim(
                        path=rel,
                        kind="malformed",
                        policy_id="",
                        owner="",
                        capability="",
                        startup="",
                    )
                )
                continue
            claim = BoundaryClaim(
                path=rel,
                kind=_metadata_value(raw, "kind"),
                policy_id=_metadata_value(raw, "policy_id"),
                owner=_metadata_value(raw, "owner"),
                capability=_metadata_value(raw, "capability"),
                startup=_metadata_value(raw, "startup"),
            )
            claims.append(claim)
    return tuple(claims)


def _task_target_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for target in task_type_index_targets(root):
        if target.path.exists():
            continue
        findings.append(
            Finding(
                code="missing-task-target",
                family="dependency",
                severity="error",
                path=_relative(root, target.source),
                target=_relative(root, target.path),
                message="task-type index entry does not resolve to a guide",
            )
        )
    return findings


def _duplicate_owner_findings(claims: tuple[BoundaryClaim, ...]) -> list[Finding]:
    owners_by_policy: dict[str, set[str]] = {}
    for claim in claims:
        if claim.kind != "policy-owner" or not claim.policy_id or not claim.owner:
            continue
        owners_by_policy.setdefault(claim.policy_id, set()).add(claim.owner)
    return [
        Finding(
            code="duplicate-policy-owner",
            family="audience",
            severity="error",
            path="model",
            target=policy_id,
            message="content-boundary policy id has multiple owners",
        )
        for policy_id, owners in sorted(owners_by_policy.items())
        if len(owners) > 1
    ]


def startup_boundary_findings(root: Path, startup_payloads: tuple[str, ...]) -> list[Finding]:
    startup = set(startup_payloads)
    return [
        Finding(
            code="eager-optional-capability",
            family="loading",
            severity="error",
            path=claim.path,
            target=claim.capability,
            message="optional capability artifact must not be in startup payloads",
        )
        for claim in _boundary_claims(root)
        if claim.kind == "optional-capability"
        and claim.startup == "excluded"
        and claim.path in startup
    ]


def content_boundary_findings(root: Path) -> list[Finding]:
    claims = _boundary_claims(root)
    findings = _task_target_findings(root)
    findings.extend(
        Finding(
            code="malformed-boundary-metadata",
            family="dependency",
            severity="error",
            path=claim.path,
            target="content-boundary",
            message="content-boundary metadata is not valid JSON",
        )
        for claim in claims
        if claim.kind == "malformed"
    )
    findings.extend(_duplicate_owner_findings(claims))
    findings.extend(startup_boundary_findings(root, startup_payloads=()))
    return sorted(findings, key=lambda item: (item.code, item.path, item.target))

from __future__ import annotations

from pathlib import Path

from model_check_contract import CodeDef, Finding, JsonValue


def _brain_operational_prose_findings(root: Path, code: CodeDef) -> list[Finding]:
    markers = (
        "agents must preserve traceability",
        "avoid destructive cleanup",
        "explicit human review",
        "prefer deterministic scripts",
        "dry-run/apply behavior",
        "invocation details, flags",
    )
    path = root / "model" / "BRAIN.common.md"
    try:
        text = path.read_text(encoding="utf-8").lower()
    except OSError:
        return []
    return [
        Finding(
            code.code,
            code.family,
            code.severity,
            "model/BRAIN.common.md",
            marker,
            "BRAIN may link to operational owners but must not own operational instructions",
        )
        for marker in markers
        if marker in text
    ]


def policy_owner_findings(root: Path, model: dict[str, JsonValue], code: CodeDef) -> list[Finding]:
    raw_owners = model.get("policy_owners", [])
    if not isinstance(raw_owners, list):
        return [
            Finding(
                code.code,
                code.family,
                code.severity,
                "model/OPERATING-MODEL.json",
                "policy_owners",
                "policy owner metadata is malformed",
            )
        ]
    rows = [row for row in raw_owners if isinstance(row, dict)]
    if len(rows) != len(raw_owners):
        return [
            Finding(
                code.code,
                code.family,
                code.severity,
                "model/OPERATING-MODEL.json",
                "policy_owners",
                "policy owner metadata is malformed",
            )
        ]
    match code.code:
        case "duplicate-policy-owner":
            owners_by_policy: dict[str, set[str]] = {}
            for row in rows:
                policy_id = row.get("policy_id")
                owner = row.get("owner")
                if isinstance(policy_id, str) and isinstance(owner, str):
                    owners_by_policy.setdefault(policy_id, set()).add(owner)
            return [
                Finding(
                    code.code,
                    code.family,
                    code.severity,
                    "model/OPERATING-MODEL.json",
                    policy_id,
                    "policy id has multiple canonical owners",
                )
                for policy_id, owners in sorted(owners_by_policy.items())
                if len(owners) > 1
            ]
        case "misplaced-policy-owner":
            findings: list[Finding] = []
            for row in rows:
                policy_id = row.get("policy_id")
                owner = row.get("owner")
                kind = row.get("kind")
                if not isinstance(policy_id, str) or not isinstance(owner, str) or not isinstance(kind, str):
                    findings.append(
                        Finding(
                            code.code,
                            code.family,
                            code.severity,
                            "model/OPERATING-MODEL.json",
                            "policy_owners",
                            "policy owner row is malformed",
                        )
                    )
                    continue
                if owner == "model/BRAIN.common.md" and kind != "conceptual":
                    findings.append(
                        Finding(
                            code.code,
                            code.family,
                            code.severity,
                            owner,
                            policy_id,
                            "BRAIN may own conceptual policy only",
                        )
                    )
            findings.extend(_brain_operational_prose_findings(root, code))
            return findings
        case _:
            return []

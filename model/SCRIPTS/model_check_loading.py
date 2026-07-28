from __future__ import annotations

import json
from pathlib import Path

from model_check_context_baseline import canonical_context_baseline
from model_check_context_payloads import session_authority_contract
from model_check_contract import CodeDef, Finding, JsonValue


def _load_context_baseline(root: Path, model: dict[str, JsonValue]) -> dict[str, JsonValue]:
    raw = model.get("context_baseline")
    if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
        return {}
    try:
        value = json.loads((root / raw["path"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _current_bytes(value: JsonValue) -> int | None:
    match value:
        case {"current_bytes": int(current_bytes)}:
            return current_bytes
        case _:
            return None


def _cap_bytes(value: JsonValue) -> int | None:
    match value:
        case {"cap_bytes": int(cap_bytes)}:
            return cap_bytes
        case _:
            return None


def _budget_findings(
    baseline: dict[str, JsonValue],
    current: dict[str, JsonValue],
    code: CodeDef,
) -> list[Finding]:
    findings: list[Finding] = []
    frozen_budgets = baseline["budgets"]
    current_budgets = current["budgets"]
    frozen_startup = frozen_budgets["startup"]
    current_startup = current_budgets["startup"]
    current_startup_bytes = _current_bytes(current_startup)
    startup_cap_bytes = _cap_bytes(frozen_startup)
    if (
        current_startup_bytes is not None
        and startup_cap_bytes is not None
        and current_startup_bytes > startup_cap_bytes
    ):
        findings.append(
            Finding(
                code=code.code,
                family=code.family,
                severity=code.severity,
                path="tests/fixtures/model-context-baseline.json",
                target="startup <= (baseline_bytes*75)//100",
                message="startup context exceeds frozen progressive-loading budget",
            )
        )
    frozen_conditional = frozen_budgets["conditional_scenarios"]
    current_conditional = current_budgets["conditional_scenarios"]
    if not isinstance(frozen_conditional, dict) or not isinstance(current_conditional, dict):
        return findings
    for scenario_id, frozen_budget in frozen_conditional.items():
        current_budget = current_conditional.get(scenario_id)
        current_scenario_bytes = _current_bytes(current_budget)
        scenario_cap_bytes = _cap_bytes(frozen_budget)
        if (
            current_scenario_bytes is not None
            and scenario_cap_bytes is not None
            and current_scenario_bytes > scenario_cap_bytes
        ):
            findings.append(
                Finding(
                    code=code.code,
                    family=code.family,
                    severity=code.severity,
                    path=str(scenario_id),
                    target="conditional <= (baseline_bytes*110+99)//100",
                    message="conditional context exceeds frozen route-payload budget",
                )
            )
    return findings


def _eager_findings(
    baseline: dict[str, JsonValue],
    current: dict[str, JsonValue],
    code: CodeDef,
) -> list[Finding]:
    route_sets = baseline["frozen_route_sets"]
    if not isinstance(route_sets, dict) or not isinstance(route_sets.get("route_terminals"), list):
        return []
    conditional = set(str(item) for item in route_sets["route_terminals"])
    startup = current["budgets"]["startup"]
    if not isinstance(startup, dict) or not isinstance(startup.get("segments"), list):
        return []
    startup_paths = {
        str(segment["path"])
        for segment in startup["segments"]
        if isinstance(segment, dict) and isinstance(segment.get("path"), str)
    }
    return [
        Finding(
            code=code.code,
            family=code.family,
            severity=code.severity,
            path=path,
            target="startup",
            message="conditional artifact is eagerly loaded during startup",
        )
        for path in sorted(conditional & startup_paths)
    ]


def loading_findings(root: Path, model: dict[str, JsonValue], code: CodeDef) -> list[Finding]:
    baseline = _load_context_baseline(root, model)
    current = canonical_context_baseline(root, model)
    match code.code:
        case "context-budget-exceeded":
            if not baseline:
                return []
            return _budget_findings(baseline, current, code)
        case "eager-skill-reference":
            if not baseline:
                return []
            return _eager_findings(baseline, current, code)
        case "eager-optional-capability":
            from model_check_content_boundaries import startup_boundary_findings

            startup = current["budgets"]["startup"]
            if not isinstance(startup, dict) or not isinstance(startup.get("segments"), list):
                return []
            startup_paths = tuple(
                str(segment["path"])
                for segment in startup["segments"]
                if isinstance(segment, dict) and isinstance(segment.get("path"), str)
            )
            return startup_boundary_findings(root, startup_paths)
        case "session-authority-conflict":
            authority = session_authority_contract(model)
            if (
                authority["authority"] == "skills/brain/scripts/session_open.py"
                and authority["fallback"] == "skills/brain/scripts/session_bootstrap.py"
            ):
                return []
            return [
                Finding(
                    code=code.code,
                    family=code.family,
                    severity=code.severity,
                    path="model/OPERATING-MODEL.json",
                    target="session_open authority, session_bootstrap compatibility fallback",
                    message="session-open routing authority is not unique",
                )
            ]
        case _:
            return []

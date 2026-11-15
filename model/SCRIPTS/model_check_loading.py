from __future__ import annotations

from pathlib import Path

from model_check_context_baseline import canonical_context_baseline, startup_segments
from model_check_context_payloads import frozen_context_baseline, session_authority_contract
from model_check_contract import CodeDef, Finding, JsonValue, UsageError


def _load_context_baseline(root: Path, model: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return frozen_context_baseline(root, model)[1]


def _section(value: JsonValue, name: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise UsageError(f"context baseline fixture budgets: {name} must be an object")
    return value


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


def _budget_finding(code: CodeDef, path: str, target: str, message: str) -> Finding:
    return Finding(
        code=code.code,
        family=code.family,
        severity=code.severity,
        path=path,
        target=target,
        message=message,
    )


def _budget_findings(
    baseline: dict[str, JsonValue],
    current: dict[str, JsonValue],
    code: CodeDef,
) -> list[Finding]:
    findings: list[Finding] = []
    fixture_path = "tests/fixtures/model-context-baseline.json"
    frozen_budgets = _section(baseline.get("budgets"), "budgets")
    current_budgets = _section(current["budgets"], "budgets")
    frozen_startup = _section(frozen_budgets.get("startup"), "startup")
    current_startup_bytes = _current_bytes(current_budgets["startup"])
    startup_cap_bytes = _cap_bytes(frozen_startup)
    if current_startup_bytes is None or startup_cap_bytes is None:
        raise UsageError("context baseline fixture startup budget lacks integer cap_bytes")
    if current_startup_bytes > startup_cap_bytes:
        findings.append(
            _budget_finding(
                code,
                fixture_path,
                "startup <= (baseline_bytes*75)//100",
                "startup context exceeds frozen progressive-loading budget",
            )
        )
    frozen_conditional = _section(frozen_budgets.get("conditional_scenarios"), "conditional_scenarios")
    current_conditional = _section(current_budgets["conditional_scenarios"], "conditional_scenarios")
    for scenario_id in sorted(set(current_conditional) - set(frozen_conditional)):
        findings.append(
            _budget_finding(
                code,
                str(scenario_id),
                "conditional <= (baseline_bytes*110+99)//100",
                "frozen route-payload budget is missing for a current scenario",
            )
        )
    for scenario_id in sorted(set(frozen_conditional) - set(current_conditional)):
        findings.append(
            _budget_finding(
                code,
                str(scenario_id),
                "conditional <= (baseline_bytes*110+99)//100",
                "frozen route-payload budget has no current scenario",
            )
        )
    for scenario_id in sorted(set(current_conditional) & set(frozen_conditional)):
        current_scenario_bytes = _current_bytes(current_conditional[scenario_id])
        scenario_cap_bytes = _cap_bytes(frozen_conditional[scenario_id])
        if current_scenario_bytes is None or scenario_cap_bytes is None:
            raise UsageError(
                f"context baseline fixture budget for {scenario_id} lacks integer cap_bytes"
            )
        if current_scenario_bytes > scenario_cap_bytes:
            findings.append(
                _budget_finding(
                    code,
                    str(scenario_id),
                    "conditional <= (baseline_bytes*110+99)//100",
                    "conditional context exceeds frozen route-payload budget",
                )
            )
    return findings


def _startup_paths() -> tuple[str, ...]:
    return tuple(
        str(segment["path"])
        for segment in startup_segments()
        if isinstance(segment.get("path"), str)
    )


def _eager_findings(baseline: dict[str, JsonValue], code: CodeDef) -> list[Finding]:
    route_sets = baseline.get("frozen_route_sets")
    if not isinstance(route_sets, dict) or not isinstance(route_sets.get("route_terminals"), list):
        raise UsageError("context baseline fixture lacks frozen_route_sets.route_terminals")
    conditional = {str(item) for item in route_sets["route_terminals"]}
    return [
        Finding(
            code=code.code,
            family=code.family,
            severity=code.severity,
            path=path,
            target="startup",
            message="conditional artifact is eagerly loaded during startup",
        )
        for path in sorted(conditional & set(_startup_paths()))
    ]


def loading_findings(root: Path, model: dict[str, JsonValue], code: CodeDef) -> list[Finding]:
    match code.code:
        case "context-budget-exceeded":
            baseline = _load_context_baseline(root, model)
            return _budget_findings(baseline, canonical_context_baseline(root, model), code)
        case "eager-skill-reference":
            return _eager_findings(_load_context_baseline(root, model), code)
        case "eager-optional-capability":
            from model_check_content_boundaries import startup_boundary_findings

            return startup_boundary_findings(root, _startup_paths())
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

from __future__ import annotations

from pathlib import Path

from model_check_context_baseline import canonical_context_baseline, startup_segments
from model_check_context_payloads import (
    FIXTURE_UNAVAILABLE,
    frozen_context_baseline,
    session_authority_contract,
)
from model_check_context_validator import operational_projection, validate_context_baseline
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
    fixture_path: str,
) -> list[Finding]:
    findings: list[Finding] = []
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


MAX_LISTED_DIFFERENCES = 6


def _projection_rows(projection: dict[str, JsonValue]) -> dict[str, JsonValue]:
    rows = dict(projection)
    scenarios = rows.pop("scenarios", None)
    if isinstance(scenarios, list):
        for index, row in enumerate(scenarios):
            label = row.get("id", index) if isinstance(row, dict) else index
            rows[f"scenarios[{label}]"] = row
    return rows


def _differences(left: JsonValue, right: JsonValue, prefix: str) -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        found: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in left or key not in right:
                found.append(child)
            else:
                found.extend(_differences(left[key], right[key], child))
        return found
    return [] if left == right else [prefix]


def _derived_mismatch_detail(
    baseline: dict[str, JsonValue], expected: dict[str, JsonValue]
) -> str:
    found = _differences(
        _projection_rows(operational_projection(baseline)),
        _projection_rows(operational_projection(expected)),
        "",
    )
    if not found:
        return ""
    found.sort(key=lambda path: not path.startswith("scenarios["))
    listed = ", ".join(found[:MAX_LISTED_DIFFERENCES])
    extra = len(found) - MAX_LISTED_DIFFERENCES
    suffix = f", and {extra} more" if extra > 0 else ""
    return f"; fixture differs from the current route payloads at {listed}{suffix}"


def _baseline_paths(model: dict[str, JsonValue]) -> tuple[str, str]:
    match model.get("context_baseline"):
        case {"path": str(path), "digest_path": str(digest_path)}:
            return path, digest_path
        case _:
            raise UsageError("context metadata missing context_baseline.path or digest_path")


def _read_digest(root: Path, digest_path: str) -> bytes:
    try:
        return (root / digest_path).read_bytes()
    except OSError as error:
        raise UsageError(f"{FIXTURE_UNAVAILABLE}: {digest_path}: {error.strerror or error}") from error


def _stale_findings(root: Path, model: dict[str, JsonValue], code: CodeDef) -> list[Finding]:
    """Report every finding of the production validator as ``context-baseline-stale``.

    The validator keeps its internal codes; each one is carried in the target and message.
    Fixture-internal budget findings (``startup-budget``, ``conditional-budget``) differ from
    ``context-budget-exceeded``, which compares the current bytes with the frozen caps, so
    both can appear for one tampered fixture and neither is dropped. Paths come from the
    manifest ``context_baseline`` entry, not from the validator's literals.
    """
    fixture_path, digest_path = _baseline_paths(model)
    raw, baseline = frozen_context_baseline(root, model)
    digest = _read_digest(root, digest_path)
    findings: list[Finding] = []
    for item in validate_context_baseline(root, model, raw, digest):
        message = f"{item.code}: {item.message}"
        if item.code == "baseline-derived-mismatch":
            message += _derived_mismatch_detail(baseline, canonical_context_baseline(root, model))
        findings.append(
            Finding(
                code=code.code,
                family=code.family,
                severity=code.severity,
                path=digest_path if item.code.startswith("digest-") else fixture_path,
                target=f"{item.code} {item.path}",
                message=message,
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
            return _budget_findings(
                baseline, canonical_context_baseline(root, model), code, _baseline_paths(model)[0]
            )
        case "context-baseline-stale":
            return _stale_findings(root, model, code)
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

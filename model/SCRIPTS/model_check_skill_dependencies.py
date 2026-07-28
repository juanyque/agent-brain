from __future__ import annotations

import json
from pathlib import Path

from model_check_context_payloads import context_contract, string_list
from model_check_contract import CodeDef, Finding, JsonValue


REFERENCE_START = "<!-- agent-brain-reference"
REFERENCE_END = "-->"
REFERENCE_SCHEMA = "agent-brain-skill-reference/v1"


def _future_skill_routes(model: dict[str, JsonValue]) -> tuple[dict[str, JsonValue], ...]:
    raw_routes = model.get("future_routes", [])
    if not isinstance(raw_routes, list):
        return ()
    return tuple(
        row
        for row in raw_routes
        if isinstance(row, dict) and isinstance(row.get("route_id"), str)
        and str(row["route_id"]).startswith("skill.")
    )


def _route_terminals(model: dict[str, JsonValue]) -> dict[str, str]:
    raw_routes = model.get("route_graph", [])
    if not isinstance(raw_routes, list):
        return {}
    terminals: dict[str, str] = {}
    for row in raw_routes:
        match row:
            case {"route_id": str(route_id), "terminal": str(terminal)}:
                terminals[route_id] = terminal
            case _:
                continue
    return terminals


def _scenario_rows(model: dict[str, JsonValue]) -> dict[str, dict[str, JsonValue]]:
    raw_scenarios = context_contract(model).get("scenario_metadata", [])
    if not isinstance(raw_scenarios, list):
        return {}
    scenarios: dict[str, dict[str, JsonValue]] = {}
    for row in raw_scenarios:
        match row:
            case {"id": str(scenario_id)} if isinstance(row, dict):
                scenarios[scenario_id] = row
            case _:
                continue
    return scenarios


def _metadata(path: Path) -> dict[str, JsonValue] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    start = text.find(REFERENCE_START)
    if start == -1:
        return None
    body_start = start + len(REFERENCE_START)
    end = text.find(REFERENCE_END, body_start)
    if end == -1:
        return None
    try:
        parsed = json.loads(text[body_start:end].strip())
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _has_reference_metadata(
    root: Path,
    rel_path: str,
    route: dict[str, JsonValue],
) -> bool:
    metadata = _metadata(root / rel_path)
    if metadata is None:
        return False
    return (
        metadata.get("schema_version") == REFERENCE_SCHEMA
        and metadata.get("route_id") == route.get("route_id")
        and metadata.get("scenario_id") == route.get("scenario_id")
        and bool(string_list(metadata.get("source_ranges", []), "source_ranges"))
        and bool(string_list(metadata.get("trigger_rules", []), "trigger_rules"))
        and bool(string_list(metadata.get("downstream_rules", []), "downstream_rules"))
    )


def _missing_reference_findings(
    root: Path,
    model: dict[str, JsonValue],
    code: CodeDef,
) -> list[Finding]:
    findings: list[Finding] = []
    for route in _future_skill_routes(model):
        payloads = string_list(route.get("final_payloads", []), "final_payloads")
        if len(payloads) != 1:
            path = str(route.get("final_terminal", "model/OPERATING-MODEL.json"))
            findings.append(
                Finding(code.code, code.family, code.severity, path, "final_payloads", "skill reference final payload mapping is malformed")
            )
            continue
        path = payloads[0]
        if not (root / path).is_file() or not _has_reference_metadata(root, path, route):
            findings.append(
                Finding(
                    code.code,
                    code.family,
                    code.severity,
                    path,
                    REFERENCE_SCHEMA,
                    "skill reference is missing or has malformed trigger/downstream metadata",
                )
            )
    return findings


def _unreachable_artifact_findings(
    model: dict[str, JsonValue],
    code: CodeDef,
) -> list[Finding]:
    contract = context_contract(model)
    declared = set(string_list(contract.get("conditional_artifacts", []), "conditional_artifacts"))
    terminals = _route_terminals(model)
    scenarios = _scenario_rows(model)
    final_paths: set[str] = set()
    findings: list[Finding] = []
    for route in _future_skill_routes(model):
        route_id = str(route["route_id"])
        scenario_id = str(route.get("scenario_id", ""))
        payloads = string_list(route.get("final_payloads", []), "final_payloads")
        final_paths.update(payloads)
        terminal = terminals.get(route_id)
        scenario = scenarios.get(scenario_id, {})
        if (
            route.get("temporary_mapping_status") != "materialized-final-payload-task-15"
            or terminal not in payloads
            or any(path not in declared for path in payloads)
            or scenario.get("payload_status") != "current-terminal"
            or scenario.get("final_payloads") != payloads
        ):
            findings.append(
                Finding(
                    code.code,
                    code.family,
                    code.severity,
                    payloads[0] if payloads else route_id,
                    route_id,
                    "skill conditional artifact is not reachable through materialized route/scenario/final mapping",
                )
            )
    for artifact in sorted(declared - final_paths - set(terminals.values())):
        if artifact.startswith("skills/brain/references/"):
            findings.append(
                Finding(
                    code.code,
                    code.family,
                    code.severity,
                    artifact,
                    "context_contract.conditional_artifacts",
                    "conditional skill artifact has no route terminal or final mapping",
                )
            )
    return findings


def skill_dependency_findings(
    root: Path,
    model: dict[str, JsonValue],
    code: CodeDef,
) -> list[Finding]:
    match code.code:
        case "missing-skill-reference":
            return _missing_reference_findings(root, model, code)
        case "unreachable-conditional-artifact":
            return _unreachable_artifact_findings(model, code)
        case _:
            return []

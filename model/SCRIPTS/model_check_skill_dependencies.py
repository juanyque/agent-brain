from __future__ import annotations

import re
from pathlib import Path

from model_check_context_payloads import artifact_route_gaps
from model_check_contract import CodeDef, Finding, JsonValue
from model_check_route_table import RouteGraphRow, route_graph_from_model


SKILL_PATH = "skills/brain/SKILL.md"
SKILL_ROOT = "skills/brain"
ROUTER_HEADING = "Conditional Reference Router"
SKILL_ROUTE_PREFIX = "skill."
ROUTER_DESTINATION_RE = re.compile(r"`(references/[^`]+)`")


def _skill_routes(model: dict[str, JsonValue]) -> tuple[RouteGraphRow, ...]:
    return tuple(
        route
        for route in route_graph_from_model(model).routes
        if route.route_id.startswith(SKILL_ROUTE_PREFIX)
    )


def _router_destinations(root: Path) -> tuple[list[str], str | None]:
    """Return the `references/...` destinations of the router table, or an error message."""
    try:
        lines = (root / SKILL_PATH).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        return [], f"skill file cannot be read: {error}"
    start = next(
        (index + 1 for index, line in enumerate(lines) if line == f"## {ROUTER_HEADING}"),
        None,
    )
    if start is None:
        return [], f"skill file has no '{ROUTER_HEADING}' section"
    destinations: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 2:
            destinations.extend(ROUTER_DESTINATION_RE.findall(cells[1]))
    if not destinations:
        return [], f"'{ROUTER_HEADING}' section lists no references"
    return destinations, None


def _readable_file(path: Path) -> bool:
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return True


def _missing_reference_findings(
    root: Path,
    model: dict[str, JsonValue],
    code: CodeDef,
) -> list[Finding]:
    findings: list[Finding] = []
    for route in _skill_routes(model):
        if not _readable_file(root / route.terminal):
            findings.append(
                Finding(
                    code.code,
                    code.family,
                    code.severity,
                    route.terminal,
                    route.route_id,
                    "skill reference route terminal is missing or unreadable",
                )
            )
    destinations, error = _router_destinations(root)
    if error is not None:
        findings.append(
            Finding(code.code, code.family, code.severity, SKILL_PATH, ROUTER_HEADING, error)
        )
    for destination in dict.fromkeys(destinations):
        path = f"{SKILL_ROOT}/{destination}"
        if not _readable_file(root / path):
            findings.append(
                Finding(
                    code.code,
                    code.family,
                    code.severity,
                    path,
                    ROUTER_HEADING,
                    "router destination is missing or unreadable",
                )
            )
    return findings


def _unreachable_artifact_findings(
    root: Path,
    model: dict[str, JsonValue],
    code: CodeDef,
) -> list[Finding]:
    findings: list[Finding] = []
    without_route, route_without_artifact = artifact_route_gaps(model)
    for artifact in without_route:
        findings.append(
            Finding(
                code.code,
                code.family,
                code.severity,
                artifact,
                "context_contract.conditional_artifacts",
                "conditional artifact has no route terminal",
            )
        )
    for terminal in route_without_artifact:
        findings.append(
            Finding(
                code.code,
                code.family,
                code.severity,
                terminal,
                "context_contract.conditional_artifacts",
                "route terminal is not declared as a conditional artifact",
            )
        )
    destinations, error = _router_destinations(root)
    if error is not None:
        # A missing or malformed router is reported as missing-skill-reference.
        return findings
    linked = {f"{SKILL_ROOT}/{destination}" for destination in destinations}
    for route in _skill_routes(model):
        if route.terminal not in linked:
            findings.append(
                Finding(
                    code.code,
                    code.family,
                    code.severity,
                    route.terminal,
                    route.route_id,
                    "skill route terminal is not linked from the Conditional Reference Router",
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
            return _unreachable_artifact_findings(root, model, code)
        case _:
            return []

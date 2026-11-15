from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from model_check_contract import CodeDef, Finding, JsonValue, parse_metadata
from model_check_context_payloads import counter_gaps, frozen_route_triples
from model_check_git_authority import GitAuthority, git_authority
from model_check_route_table import (
    CommonRoute,
    ParsedRouteGraph,
    route_finding,
    route_graph_from_model,
    route_rows_from_common,
)


@dataclass(frozen=True, slots=True)
class AudienceHeader:
    audience: str
    purpose: str


TASK_TYPE_ROUTE = CommonRoute(
    route_id="task-types.index",
    scenario_id="scenario.task-types",
    trigger="User describes a task that may match a known task-type",
    load="model/TASK_TYPES/TASK_TYPES.common.md",
)


def _expected_common_routes(
    model: dict[str, JsonValue],
    route_graph: ParsedRouteGraph | None = None,
) -> tuple[CommonRoute, ...]:
    routes: list[CommonRoute] = []
    parsed = route_graph if route_graph is not None else route_graph_from_model(model)
    for row in parsed.routes:
        if not row.route_id.startswith("rule."):
            continue
        routes.append(
            CommonRoute(
                route_id=row.route_id,
                scenario_id=row.scenario_id,
                trigger="",
                load=row.terminal,
            )
        )
    routes.append(TASK_TYPE_ROUTE)
    return tuple(routes)


def resolved_route_table(
    root: Path,
    model: dict[str, JsonValue],
    common_path: Path,
) -> tuple[CommonRoute, ...]:
    rows = route_rows_from_common(common_path)
    resolved: list[CommonRoute] = []
    for expected in _expected_common_routes(model, route_graph_from_model(model)):
        route = rows.get(expected.route_id)
        if route is None:
            continue
        if route.scenario_id != expected.scenario_id or route.load != expected.load:
            continue
        if not (root / route.load).exists():
            continue
        resolved.append(route)
    return tuple(sorted(resolved, key=lambda item: item.route_id))


def route_target_findings(
    root: Path,
    model: dict[str, JsonValue],
    common_path: Path,
) -> list[Finding]:
    rows = route_rows_from_common(common_path)
    code_metadata = {code.code: code for code in parse_metadata(model).codes}
    route_graph = route_graph_from_model(model, code_metadata)
    findings = list(route_graph.findings)
    for route in route_graph.routes:
        terminal = route.terminal
        if (root / terminal).exists():
            continue
        if route.route_id.startswith("skill."):
            continue
        if route.route_id == "rule.attachments":
            finding = route_finding(
                code_metadata,
                "unmapped-cluster",
                terminal,
                route.route_id,
                "attachment route terminal is missing",
            )
            if finding is not None:
                findings.append(finding)
            continue
        finding = route_finding(
            code_metadata,
            "missing-route-target",
            terminal,
            route.route_id,
            "route terminal is missing",
        )
        if finding is not None:
            findings.append(finding)
    for expected in _expected_common_routes(model, route_graph):
        row = rows.get(expected.route_id)
        if row is None or row.scenario_id != expected.scenario_id or row.load != expected.load:
            finding = route_finding(
                code_metadata,
                "missing-route-target",
                expected.load,
                expected.route_id,
                "common rule trigger row does not resolve",
            )
            if finding is not None:
                findings.append(finding)
    deduped: dict[tuple[str, str, str], Finding] = {}
    for finding in findings:
        deduped[(finding.code, finding.path, finding.target)] = finding
    return list(deduped.values())


def orphan_rule_findings(
    root: Path,
    model: dict[str, JsonValue],
    common_path: Path,
    extra_rule_paths: tuple[str, ...] = (),
) -> list[Finding]:
    route_terminals = {
        route.terminal
        for route in route_graph_from_model(model).routes
        if route.route_id.startswith("rule.")
    }
    route_terminals.add(TASK_TYPE_ROUTE.load)
    common_rows = {route.load for route in route_rows_from_common(common_path).values()}
    actual_rules = {
        path.relative_to(root).as_posix()
        for path in (root / "model").glob("RULES-*.common.md")
    }
    actual_rules.update(extra_rule_paths)
    orphans = sorted(actual_rules - route_terminals - common_rows)
    code_metadata = {code.code: code for code in parse_metadata(model).codes}
    return [
        finding
        for path in orphans
        if (
            finding := route_finding(
                code_metadata,
                "orphan-model-artifact",
                path,
                "route_graph",
                "common rule file is not mapped by a route",
            )
        )
        is not None
    ]


def audience_header(common_path: Path) -> AudienceHeader:
    values: dict[str, str] = {}
    for line in common_path.read_text(encoding="utf-8").splitlines()[:8]:
        match line.split(":", 1):
            case ["Audience", value]:
                values["audience"] = value.strip()
            case ["Purpose", value]:
                values["purpose"] = value.strip()
            case _:
                continue
    return AudienceHeader(audience=values.get("audience", ""), purpose=values.get("purpose", ""))


def frozen_route_findings(
    root: Path,
    model: dict[str, JsonValue],
    code: CodeDef,
) -> list[Finding]:
    """Compare the route graph with the scenario triples frozen in the context fixture."""
    graph = route_graph_from_model(model)
    if graph.problems:
        return []  # reported by the route-target findings of the graph itself
    actual = [" | ".join((row.scenario_id, row.route_id, row.terminal)) for row in graph.routes]
    frozen = [" | ".join(triple) for triple in frozen_route_triples(root, model)]
    missing, unexpected = counter_gaps(actual, frozen)
    return [
        Finding(
            code=code.code,
            family=code.family,
            severity=code.severity,
            path="model/OPERATING-MODEL.json",
            target=triple,
            message=message,
        )
        for triples, message in (
            (missing, "frozen context-fixture route is missing from route_graph"),
            (unexpected, "route_graph route is not in the frozen context fixture"),
        )
        for triple in triples
    ]

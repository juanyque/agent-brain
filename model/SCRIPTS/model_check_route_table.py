from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from model_check_contract import CodeDef, Finding, JsonValue


@dataclass(frozen=True, slots=True)
class CommonRoute:
    route_id: str
    scenario_id: str
    trigger: str
    load: str


@dataclass(frozen=True, slots=True)
class RouteGraphRow:
    route_id: str
    scenario_id: str
    terminal: str


@dataclass(frozen=True, slots=True)
class RouteProblem:
    code: str
    target: str
    message: str


@dataclass(frozen=True, slots=True)
class ParsedRouteGraph:
    routes: tuple[RouteGraphRow, ...]
    problems: tuple[RouteProblem, ...]
    findings: tuple[Finding, ...]


def route_finding(
    codes: dict[str, CodeDef],
    code: str,
    path: str,
    target: str,
    message: str,
) -> Finding | None:
    definition = codes.get(code)
    if definition is None:
        return None
    return Finding(
        code=definition.code,
        family=definition.family,
        severity=definition.severity,
        path=path,
        target=target,
        message=message,
    )


def _parse_route_graph(
    model: dict[str, JsonValue],
) -> tuple[tuple[RouteGraphRow, ...], tuple[RouteProblem, ...]]:
    raw_routes = model.get("route_graph")
    if not isinstance(raw_routes, list):
        return (), (
            RouteProblem(
                "malformed-route-metadata",
                "route_graph",
                "route_graph must be a list of route rows",
            ),
        )
    routes: list[RouteGraphRow] = []
    problems: list[RouteProblem] = []
    seen: dict[str, set[str]] = {"route_id": set(), "scenario_id": set(), "terminal": set()}
    for index, row in enumerate(raw_routes):
        match row:
            case {"route_id": str(route_id), "scenario_id": str(scenario_id), "terminal": str(terminal)}:
                if not route_id or not scenario_id or not terminal:
                    problems.append(
                        RouteProblem(
                            "malformed-route-metadata",
                            f"route_graph[{index}]",
                            "route row requires non-empty route_id, scenario_id, and terminal strings",
                        )
                    )
                    continue
                duplicated = [
                    (field, value)
                    for field, value in (
                        ("route_id", route_id),
                        ("scenario_id", scenario_id),
                        ("terminal", terminal),
                    )
                    if value in seen[field]
                ]
                for field, value in duplicated:
                    problems.append(
                        RouteProblem(
                            "duplicate-route-id",
                            value,
                            f"route_graph {field} must be unique",
                        )
                    )
                if duplicated:
                    continue
                seen["route_id"].add(route_id)
                seen["scenario_id"].add(scenario_id)
                seen["terminal"].add(terminal)
                routes.append(RouteGraphRow(route_id, scenario_id, terminal))
            case _:
                problems.append(
                    RouteProblem(
                        "malformed-route-metadata",
                        f"route_graph[{index}]",
                        "route row requires route_id, scenario_id, and terminal strings",
                    )
                )
    return tuple(routes), tuple(problems)


def route_graph_from_model(
    model: dict[str, JsonValue],
    codes: dict[str, CodeDef] | None = None,
) -> ParsedRouteGraph:
    route_codes = codes if codes is not None else {}
    routes, problems = _parse_route_graph(model)
    findings = tuple(
        finding
        for problem in problems
        if (
            finding := route_finding(
                route_codes,
                problem.code,
                "model/OPERATING-MODEL.json",
                problem.target,
                problem.message,
            )
        )
        is not None
    )
    return ParsedRouteGraph(routes=routes, problems=problems, findings=findings)


def _pipe_cells(line: str) -> tuple[str, ...]:
    return tuple(cell.strip() for cell in line.strip().strip("|").split("|"))


def _section_lines(text: str, heading: str) -> tuple[str, ...]:
    lines = text.splitlines()
    start = next(
        (index + 1 for index, line in enumerate(lines) if line == f"## {heading}"),
        None,
    )
    if start is None:
        return ()
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return tuple(lines[start:end])


def route_rows_from_common(common_path: Path) -> dict[str, CommonRoute]:
    table_lines = [
        line
        for line in _section_lines(common_path.read_text(encoding="utf-8"), "Rule triggers")
        if line.startswith("|")
    ]
    if len(table_lines) < 3:
        return {}
    headers = _pipe_cells(table_lines[0])
    if headers != ("Route", "Scenario", "Trigger", "Load"):
        return {}
    rows: dict[str, CommonRoute] = {}
    for line in table_lines[2:]:
        cells = _pipe_cells(line)
        if len(cells) != len(headers):
            continue
        route = CommonRoute(
            route_id=cells[0],
            scenario_id=cells[1],
            trigger=cells[2],
            load=cells[3],
        )
        rows[route.route_id] = route
    return rows

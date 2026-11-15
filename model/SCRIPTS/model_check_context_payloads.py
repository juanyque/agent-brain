from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from model_check_contract import JsonValue, UsageError
from model_check_route_table import route_graph_from_model


@dataclass(frozen=True, slots=True)
class PayloadResolution:
    raw_segments: tuple[bytes, ...]
    segments: tuple[dict[str, JsonValue], ...]
    disk_reads: tuple[str, ...]


def string_list(value: JsonValue, field: str) -> list[str]:
    if not isinstance(value, list):
        raise UsageError(f"context metadata {field} must be a list")
    items = [item for item in value if isinstance(item, str)]
    if len(items) != len(value):
        raise UsageError(f"context metadata {field} entries must be strings")
    return items


def context_contract(model: dict[str, JsonValue]) -> dict[str, JsonValue]:
    raw_contract = model.get("context_contract")
    if not isinstance(raw_contract, dict):
        raise UsageError("context metadata missing context_contract")
    return raw_contract


def session_authority_contract(model: dict[str, JsonValue]) -> dict[str, str]:
    raw_authority = context_contract(model).get("session_authority")
    match raw_authority:
        case {
            "authority": str(authority),
            "fallback": str(fallback),
            "fallback_role": "compatibility-fallback",
        }:
            return {
                "authority": authority,
                "fallback": fallback,
                "fallback_role": "compatibility-fallback",
            }
        case _:
            raise UsageError("context metadata session_authority is malformed")


FIXTURE_UNAVAILABLE = "context baseline fixture is unavailable"


def route_rows(model: dict[str, JsonValue]) -> list[dict[str, str]]:
    graph = route_graph_from_model(model)
    if graph.problems:
        problem = graph.problems[0]
        raise UsageError(f"context route_graph is invalid: {problem.target}: {problem.message}")
    return [
        {"route_id": row.route_id, "scenario_id": row.scenario_id, "terminal": row.terminal}
        for row in graph.routes
    ]


def route_triples(model: dict[str, JsonValue]) -> list[tuple[str, str, str]]:
    return [(row["scenario_id"], row["route_id"], row["terminal"]) for row in route_rows(model)]


def frozen_context_baseline(
    root: Path,
    model: dict[str, JsonValue],
) -> tuple[bytes, dict[str, JsonValue]]:
    """Return the raw bytes and parsed value of the frozen fixture, failing closed."""
    match model.get("context_baseline"):
        case {"path": str(rel_path)}:
            pass
        case _:
            raise UsageError("context metadata missing context_baseline.path")
    try:
        raw = (root / rel_path).read_bytes()
    except OSError as error:
        raise UsageError(f"{FIXTURE_UNAVAILABLE}: {rel_path}: {error.strerror or error}") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UsageError(f"{FIXTURE_UNAVAILABLE}: {rel_path}: {error}") from error
    if not isinstance(value, dict):
        raise UsageError(f"{FIXTURE_UNAVAILABLE}: {rel_path}: root must be an object")
    return raw, value


def frozen_route_triples(root: Path, model: dict[str, JsonValue]) -> list[tuple[str, str, str]]:
    _raw, baseline = frozen_context_baseline(root, model)
    scenarios = baseline.get("scenarios")
    if not isinstance(scenarios, list):
        raise UsageError(f"{FIXTURE_UNAVAILABLE}: scenarios must be a list")
    triples: list[tuple[str, str, str]] = []
    for row in scenarios:
        match row:
            case {"id": str(scenario_id), "route_id": str(route_id), "terminal": str(terminal)}:
                triples.append((scenario_id, route_id, terminal))
            case _:
                raise UsageError(f"{FIXTURE_UNAVAILABLE}: scenario row is malformed")
    return triples


def counter_gaps(actual: list[str], expected: list[str]) -> tuple[list[str], list[str]]:
    """Return (missing, unexpected) entries; duplicates stay visible."""
    wanted = Counter(expected)
    found = Counter(actual)
    return sorted((wanted - found).elements()), sorted((found - wanted).elements())


def artifact_route_gaps(model: dict[str, JsonValue]) -> tuple[list[str], list[str]]:
    """Return (artifacts without a route terminal, route terminals not declared as artifacts)."""
    artifacts = string_list(
        context_contract(model).get("conditional_artifacts", []),
        "conditional_artifacts",
    )
    terminals = [row.terminal for row in route_graph_from_model(model).routes]
    return counter_gaps(terminals, artifacts)


def _file_segment(root: Path, rel_path: str) -> tuple[bytes, dict[str, JsonValue]]:
    try:
        raw = (root / rel_path).read_bytes()
    except OSError as error:
        raise UsageError(
            f"route terminal cannot be read: {rel_path}: {error.strerror or error}"
        ) from error
    return raw, {
        "bytes": len(raw),
        "id": rel_path,
        "kind": "disk-file",
        "lines": len(raw.splitlines()),
        "path": rel_path,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def resolve_segments(root: Path, route: dict[str, str]) -> PayloadResolution:
    terminal = route["terminal"]
    raw, segment = _file_segment(root, terminal)
    return PayloadResolution((raw,), (segment,), (terminal,))

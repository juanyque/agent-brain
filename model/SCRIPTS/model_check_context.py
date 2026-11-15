from __future__ import annotations

import hashlib
import sys
from collections import Counter
from pathlib import Path

from model_check_context_payloads import (
    context_contract,
    counter_gaps,
    frozen_route_triples,
    resolve_segments,
    route_rows,
    route_triples,
    string_list,
)
from model_check_contract import JsonValue


REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_SCRIPTS = REPO_ROOT / "skills" / "brain" / "scripts"
if str(SESSION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SESSION_SCRIPTS))

from session_open import collect_session_digest_state  # noqa: E402
from session_digest import fixed_session_digest_request, render_session_digest  # noqa: E402


RUNTIME_PROJECT_AGENTS_BYTES = (
    b"# Runtime-injected project AGENTS\n"
    b"brain_root: /fixture/brain\n"
    b"cwd: /fixture/project\n"
    b"injected: true\n"
)


def runtime_segments() -> list[dict[str, JsonValue]]:
    raw = RUNTIME_PROJECT_AGENTS_BYTES
    return [
        {
            "bytes": len(raw),
            "id": "runtime.project-agents.injected",
            "kind": "runtime-injected",
            "lines": len(raw.splitlines()),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    ]


def fixture_session_digest() -> dict[str, JsonValue]:
    text = render_session_digest(collect_session_digest_state(fixed_session_digest_request()))
    raw = text.encode("utf-8")
    return {
        "bytes": len(raw),
        "lines": len(text.splitlines()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "text": text,
    }


def _duplicates(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _triple_labels(triples: list[tuple[str, str, str]]) -> list[str]:
    return [" | ".join(triple) for triple in triples]


def route_coverage(root: Path, model: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Computed coverage of routes, conditional artifacts and the frozen fixture.

    Lists and counters are compared before any set conversion so that duplicates stay visible.
    """
    contract = context_contract(model)
    artifacts = string_list(contract.get("conditional_artifacts", []), "conditional_artifacts")
    routes = route_rows(model)
    route_ids = [route["route_id"] for route in routes]
    scenario_ids = [route["scenario_id"] for route in routes]
    terminals = [route["terminal"] for route in routes]
    triples = _triple_labels(route_triples(model))
    frozen = _triple_labels(frozen_route_triples(root, model))
    inventory = string_list(model.get("governed_inventory", []), "governed_inventory")
    audience_rows = model.get("audience_contract", [])
    audience = [
        row["path"]
        for row in (audience_rows if isinstance(audience_rows, list) else [])
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    ]
    mismatches: dict[str, JsonValue] = {}
    for name, values in (
        ("route_ids", route_ids),
        ("scenario_ids", scenario_ids),
        ("route_terminals", terminals),
        ("conditional_artifacts", artifacts),
        ("frozen_route_triples", frozen),
    ):
        duplicated = _duplicates(values)
        if duplicated:
            mismatches[f"duplicate_{name}"] = duplicated
    without_route, without_artifact = counter_gaps(terminals, artifacts)
    if without_route or without_artifact:
        mismatches["conditional_artifacts"] = {
            "route_without_artifact": without_artifact,
            "without_route": without_route,
        }
    missing_triples, unexpected_triples = counter_gaps(triples, frozen)
    if missing_triples or unexpected_triples:
        mismatches["route_triples"] = {
            "missing_from_route_graph": missing_triples,
            "not_in_frozen_fixture": unexpected_triples,
        }
    ungoverned = sorted(set(terminals) - set(inventory))
    if ungoverned:
        mismatches["ungoverned_terminals"] = ungoverned
    without_audience = sorted(set(terminals) - set(audience))
    if without_audience:
        mismatches["terminals_without_audience"] = without_audience
    return {
        "conditional_artifacts": sorted(artifacts),
        "mismatches": mismatches,
        "route_terminals": sorted(terminals),
        "scenario_ids": sorted(scenario_ids),
        "valid": not mismatches,
    }


def _scenario_report(
    root: Path,
    route: dict[str, str],
    conditional_artifacts: list[str],
) -> dict[str, JsonValue]:
    resolved = resolve_segments(root, route)
    included = [str(segment["id"]) for segment in resolved.segments]
    payload = b"".join(resolved.raw_segments)
    return {
        "disk_reads": list(resolved.disk_reads),
        "excluded_artifacts": sorted(
            artifact for artifact in conditional_artifacts if artifact not in included
        ),
        "model_visible_bytes": len(payload),
        "model_visible_sha256": hashlib.sha256(payload).hexdigest(),
        "route_id": route["route_id"],
        "scenario_id": route["scenario_id"],
        "segment_ids": included,
        "segments": list(resolved.segments),
        "selectivity_delta": {
            "excluded_count": len(conditional_artifacts) - len(included),
            "included": included,
            "included_count": len(included),
        },
        "terminal": route["terminal"],
    }


def build_context_report(root: Path, model: dict[str, JsonValue], source_digest: str) -> dict[str, JsonValue]:
    contract = context_contract(model)
    conditional_artifacts = string_list(
        contract.get("conditional_artifacts", []),
        "conditional_artifacts",
    )
    routes = route_rows(model)
    terminals = sorted({route["terminal"] for route in routes})
    scenarios = [_scenario_report(root, route, conditional_artifacts) for route in routes]
    digest = fixture_session_digest()
    runtime = runtime_segments()
    total_model_visible_bytes = (
        sum(int(scenario["model_visible_bytes"]) for scenario in scenarios)
        + int(digest["bytes"])
        + sum(int(segment["bytes"]) for segment in runtime)
    )
    return {
        "byte_accounting": {
            "fixture_session_digest_sha256": digest["sha256"],
            "model_visible_bytes": total_model_visible_bytes,
            "runtime_project_agents_sha256": runtime[0]["sha256"],
        },
        "fixture_session_digest": digest,
        "route_coverage": route_coverage(root, model),
        "runtime_segments": runtime,
        "scenarios": sorted(scenarios, key=lambda row: str(row["scenario_id"])),
        "source_digest": source_digest,
        "totals": {
            "conditional_artifact_count": len(conditional_artifacts),
            "route_count": len(routes),
            "scenario_count": len(scenarios),
            "terminal_count": len(terminals),
        },
    }

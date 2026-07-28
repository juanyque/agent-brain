from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from model_check_context_payloads import (
    PayloadRange,
    baseline_commit,
    context_contract,
    payload_ranges,
    resolve_segments,
    route_rows,
    scenario_metadata,
    string_list,
)
from model_check_contract import JsonValue, UsageError


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


def _future_route_sets(model: dict[str, JsonValue]) -> dict[str, list[str]]:
    raw_future_routes = model.get("future_routes", [])
    if not isinstance(raw_future_routes, list):
        raise UsageError("context future_routes must be a list")
    final_payloads: list[str] = []
    temporary_payloads: list[str] = []
    baseline_ids: list[str] = []
    for row in raw_future_routes:
        match row:
            case {
                "baseline_id": str(baseline_id),
                "final_payloads": list(raw_final_payloads),
                "temporary_payloads": list(raw_temporary_payloads),
            }:
                baseline_ids.append(baseline_id)
                final_payloads.extend(item for item in raw_final_payloads if isinstance(item, str))
                temporary_payloads.extend(
                    item for item in raw_temporary_payloads if isinstance(item, str)
                )
            case _:
                raise UsageError("context future route is malformed")
    return {
        "future_baseline_ids": sorted(set(baseline_ids)),
        "future_final_payloads": sorted(set(final_payloads)),
        "future_temporary_payloads": sorted(set(temporary_payloads)),
    }


def _set_equality(
    model: dict[str, JsonValue],
    terminals: list[str],
    scenario_ids: list[str],
) -> dict[str, JsonValue]:
    contract = context_contract(model)
    declared = contract.get("set_equality", {})
    if not isinstance(declared, dict):
        raise UsageError("context metadata set_equality must be an object")
    future_sets = _future_route_sets(model)
    authoritative_baseline_ids = sorted({f"baseline.{baseline_commit(model)}"})
    actual = {
        "discovered_conditional_artifacts": sorted(
            string_list(contract.get("conditional_artifacts", []), "conditional_artifacts")
        ),
        "frozen_baseline_ids": authoritative_baseline_ids,
        "route_terminals": terminals,
        "scenario_ids": scenario_ids,
        **future_sets,
    }
    expected = {
        "discovered_conditional_artifacts": terminals,
        "future_baseline_ids": authoritative_baseline_ids,
        "future_final_payloads": string_list(
            declared.get("future_final_payloads", []),
            "future_final_payloads",
        ),
        "future_temporary_payloads": string_list(
            declared.get("future_temporary_payloads", []),
            "future_temporary_payloads",
        ),
        "route_terminals": string_list(declared.get("route_terminals", []), "route_terminals"),
        "scenario_ids": string_list(declared.get("scenario_ids", []), "scenario_ids"),
    }
    mismatches = {
        key: {"actual": actual[key], "expected": expected[key]}
        for key in expected
        if actual[key] != expected[key]
    }
    return {**actual, "mismatches": mismatches, "valid": not mismatches}


def _scenario_report(
    root: Path,
    commit: str,
    route: dict[str, str],
    metadata: dict[str, JsonValue] | None,
    ranges: dict[str, PayloadRange],
    conditional_artifacts: list[str],
) -> dict[str, JsonValue]:
    resolved = resolve_segments(root, commit, route, metadata, ranges)
    included = [str(segment["id"]) for segment in resolved.segments]
    payload = b"".join(resolved.raw_segments)
    return {
        "disk_reads": list(resolved.disk_reads),
        "excluded_artifacts": sorted(
            artifact for artifact in conditional_artifacts if artifact not in included
        ),
        "model_visible_bytes": len(payload),
        "model_visible_sha256": hashlib.sha256(payload).hexdigest(),
        "payload_status": resolved.status,
        "resolution": resolved.resolution,
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
    commit = baseline_commit(model)
    contract = context_contract(model)
    conditional_artifacts = string_list(
        contract.get("conditional_artifacts", []),
        "conditional_artifacts",
    )
    routes = route_rows(model)
    terminals = sorted({route["terminal"] for route in routes})
    scenario_ids = sorted({route["scenario_id"] for route in routes})
    metadata_by_id = scenario_metadata(model)
    ranges = payload_ranges(model)
    scenarios = [
        _scenario_report(
            root,
            commit,
            route,
            metadata_by_id.get(route["scenario_id"]),
            ranges,
            conditional_artifacts,
        )
        for route in routes
    ]
    digest = fixture_session_digest()
    runtime = runtime_segments()
    future_route_count = len(model.get("future_routes", []))
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
        "runtime_segments": runtime,
        "scenarios": sorted(scenarios, key=lambda row: str(row["scenario_id"])),
        "set_equality": _set_equality(model, terminals, scenario_ids),
        "source_digest": source_digest,
        "totals": {
            "conditional_artifact_count": len(conditional_artifacts),
            "future_route_count": future_route_count,
            "scenario_count": len(scenarios),
            "terminal_count": len(terminals),
        },
    }

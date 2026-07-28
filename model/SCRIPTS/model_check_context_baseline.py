from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from model_check_context import RUNTIME_PROJECT_AGENTS_BYTES, fixture_session_digest
from model_check_context_payloads import (
    PayloadRange,
    baseline_commit,
    context_contract,
    payload_ranges,
    resolve_segments,
    route_rows,
    scenario_metadata,
)
from model_check_contract import JsonValue


SCHEMA_VERSION = "agent-brain-model-context-baseline/v1"
STARTUP_CAP_FORMULA = "(baseline_bytes*75)//100"
CONDITIONAL_CAP_FORMULA = "(baseline_bytes*110+99)//100"


def canonical_json_bytes(value: JsonValue) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _normalized_text(raw: bytes) -> str:
    return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _segment_row(
    segment: dict[str, JsonValue],
    raw: bytes,
    ordinal: int,
) -> dict[str, JsonValue]:
    content = _normalized_text(raw)
    encoded = content.encode("utf-8")
    row: dict[str, JsonValue] = {
        "bytes": len(encoded),
        "content": content,
        "id": str(segment["id"]),
        "kind": str(segment["kind"]),
        "lines": len(content.splitlines()),
        "ordinal": ordinal,
        "path": str(segment.get("path", "")),
        "sha256": digest_bytes(encoded),
    }
    if "range" in segment:
        row["range"] = str(segment["range"])
    return row


def _runtime_segment() -> dict[str, JsonValue]:
    content = _normalized_text(RUNTIME_PROJECT_AGENTS_BYTES)
    encoded = content.encode("utf-8")
    return {
        "bytes": len(encoded),
        "content": content,
        "id": "runtime.project-agents.injected",
        "kind": "runtime-injected",
        "lines": len(content.splitlines()),
        "ordinal": 0,
        "path": "<runtime>",
        "sha256": digest_bytes(encoded),
    }


def _digest_segment() -> dict[str, JsonValue]:
    digest = fixture_session_digest()
    content = _normalized_text(str(digest["text"]).encode("utf-8"))
    encoded = content.encode("utf-8")
    return {
        "bytes": len(encoded),
        "content": content,
        "id": "session.open.digest",
        "kind": "session-digest",
        "lines": len(content.splitlines()),
        "ordinal": 1,
        "path": "<session_open>",
        "sha256": digest_bytes(encoded),
    }


def _scenario_row(
    root: Path,
    commit: str,
    route: dict[str, str],
    metadata: dict[str, JsonValue] | None,
    ranges: dict[str, PayloadRange],
) -> dict[str, JsonValue]:
    resolved = resolve_segments(root, commit, route, metadata, ranges)
    segments = [
        _segment_row(segment, raw, ordinal)
        for ordinal, (segment, raw) in enumerate(zip(resolved.segments, resolved.raw_segments))
    ]
    content = "".join(str(segment["content"]) for segment in segments)
    encoded = content.encode("utf-8")
    return {
        "bytes": len(encoded),
        "disk_reads": list(resolved.disk_reads),
        "id": route["scenario_id"],
        "lines": len(content.splitlines()),
        "payload_status": resolved.status,
        "resolution": resolved.resolution,
        "route_id": route["route_id"],
        "segments": segments,
        "sha256": digest_bytes(encoded),
        "terminal": route["terminal"],
        "terminal_load_count": 1,
    }


def _budgets(scenarios: list[dict[str, JsonValue]]) -> dict[str, JsonValue]:
    baseline_bytes = sum(int(scenario["bytes"]) for scenario in scenarios)
    startup_segments = [_runtime_segment(), _digest_segment()]
    startup_bytes = sum(int(segment["bytes"]) for segment in startup_segments)
    conditional: dict[str, JsonValue] = {}
    for scenario in scenarios:
        scenario_bytes = int(scenario["bytes"])
        scenario_id = str(scenario["id"])
        conditional[scenario_id] = {
            "baseline_bytes": scenario_bytes,
            "cap_bytes": (scenario_bytes * 110 + 99) // 100,
            "current_bytes": scenario_bytes,
            "scenario_id": scenario_id,
        }
    return {
        "conditional_cap_formula": CONDITIONAL_CAP_FORMULA,
        "conditional_scenarios": conditional,
        "startup": {
            "baseline_bytes": baseline_bytes,
            "cap_bytes": (baseline_bytes * 75) // 100,
            "cap_formula": STARTUP_CAP_FORMULA,
            "current_bytes": startup_bytes,
            "segments": startup_segments,
        },
    }


def canonical_context_baseline(root: Path, model: dict[str, JsonValue]) -> dict[str, JsonValue]:
    commit = baseline_commit(model)
    metadata_by_id = scenario_metadata(model)
    ranges = payload_ranges(model)
    scenarios = sorted(
        (
            _scenario_row(
                root,
                commit,
                route,
                metadata_by_id.get(route["scenario_id"]),
                ranges,
            )
            for route in route_rows(model)
        ),
        key=lambda row: str(row["id"]),
    )
    return {
        "baseline_commit": commit,
        "budgets": _budgets(scenarios),
        "fixed_fixture_state": context_contract(model)["fixed_fixture_state"],
        "frozen_route_sets": {
            "route_terminals": sorted(str(route["terminal"]) for route in route_rows(model)),
            "scenario_ids": [str(scenario["id"]) for scenario in scenarios],
        },
        "scenarios": scenarios,
        "schema_version": SCHEMA_VERSION,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate canonical model-context baseline JSON.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--model", default="model/OPERATING-MODEL.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--digest-output", required=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    model_path = Path(args.model)
    if not model_path.is_absolute():
        model_path = root / model_path
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if not isinstance(model, dict):
        raise TypeError("metadata root must be an object")
    raw = canonical_json_bytes(canonical_context_baseline(root, model))
    Path(args.output).write_bytes(raw)
    Path(args.digest_output).write_text(digest_bytes(raw) + "\n", encoding="ascii")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from model_check_contract import JsonValue, UsageError


@dataclass(frozen=True, slots=True)
class PayloadRange:
    id: str
    path: str
    start_line: int
    end_line: int
    bytes: int
    lines: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PayloadResolution:
    status: str
    resolution: str
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


def baseline_commit(model: dict[str, JsonValue]) -> str:
    baseline = model.get("baseline")
    if not isinstance(baseline, dict) or not isinstance(baseline.get("commit"), str):
        raise UsageError("context metadata missing baseline commit")
    return baseline["commit"]


def payload_ranges(model: dict[str, JsonValue]) -> dict[str, PayloadRange]:
    raw_ranges = context_contract(model).get("payload_source_ranges", [])
    if not isinstance(raw_ranges, list):
        raise UsageError("context metadata payload_source_ranges must be a list")
    ranges: dict[str, PayloadRange] = {}
    for row in raw_ranges:
        match row:
            case {
                "id": str(range_id),
                "path": str(path),
                "start_line": int(start_line),
                "end_line": int(end_line),
                "bytes": int(byte_count),
                "lines": int(line_count),
                "sha256": str(digest),
            }:
                ranges[range_id] = PayloadRange(
                    id=range_id,
                    path=path,
                    start_line=start_line,
                    end_line=end_line,
                    bytes=byte_count,
                    lines=line_count,
                    sha256=digest,
                )
            case _:
                raise UsageError("context metadata payload range is malformed")
    return ranges


def scenario_metadata(model: dict[str, JsonValue]) -> dict[str, dict[str, JsonValue]]:
    raw_scenarios = context_contract(model).get("scenario_metadata", [])
    if not isinstance(raw_scenarios, list):
        raise UsageError("context metadata scenario_metadata must be a list")
    scenarios: dict[str, dict[str, JsonValue]] = {}
    for row in raw_scenarios:
        match row:
            case {"id": str(scenario_id)}:
                if not isinstance(row, dict):
                    raise UsageError("context scenario metadata must be an object")
                scenarios[scenario_id] = row
            case _:
                raise UsageError("context scenario metadata is malformed")
    return scenarios


def route_rows(model: dict[str, JsonValue]) -> list[dict[str, str]]:
    raw_routes = model.get("route_graph", [])
    if not isinstance(raw_routes, list):
        raise UsageError("context route_graph must be a list")
    routes: list[dict[str, str]] = []
    for row in raw_routes:
        match row:
            case {
                "route_id": str(route_id),
                "scenario_id": str(scenario_id),
                "terminal": str(terminal),
            }:
                routes.append(
                    {
                        "route_id": route_id,
                        "scenario_id": scenario_id,
                        "terminal": terminal,
                    }
                )
            case _:
                raise UsageError("context route_graph entry is malformed")
    return routes


def _git_show(root: Path, commit: str, rel_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{rel_path}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise UsageError(f"baseline payload cannot be read: {rel_path}: {message}")
    return result.stdout


def _baseline_segment(root: Path, commit: str, payload: PayloadRange) -> tuple[bytes, dict[str, JsonValue]]:
    lines = _git_show(root, commit, payload.path).splitlines(keepends=True)
    raw = b"".join(lines[payload.start_line - 1 : payload.end_line])
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != payload.bytes or digest != payload.sha256:
        raise UsageError(f"baseline payload range changed: {payload.id}")
    return raw, {
        "bytes": len(raw),
        "id": payload.id,
        "kind": "baseline-range",
        "lines": payload.lines,
        "path": payload.path,
        "range": f"{payload.start_line}-{payload.end_line}",
        "sha256": digest,
    }


def _file_segment(root: Path, rel_path: str) -> tuple[bytes, dict[str, JsonValue]]:
    raw = (root / rel_path).read_bytes()
    return raw, {
        "bytes": len(raw),
        "id": rel_path,
        "kind": "disk-file",
        "lines": len(raw.splitlines()),
        "path": rel_path,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def resolve_segments(
    root: Path,
    commit: str,
    route: dict[str, str],
    scenario: dict[str, JsonValue] | None,
    ranges: dict[str, PayloadRange],
) -> PayloadResolution:
    terminal = route["terminal"]
    if (root / terminal).exists():
        raw, segment = _file_segment(root, terminal)
        return PayloadResolution("current-terminal", "final-file", (raw,), (segment,), (terminal,))
    if scenario is None:
        raise UsageError(f"context route has no payload: {route['scenario_id']}")
    raw_segments: list[bytes] = []
    segments: list[dict[str, JsonValue]] = []
    disk_reads: list[str] = []
    for range_id in string_list(scenario.get("payload_source_ranges", []), "payload_source_ranges"):
        payload = ranges.get(range_id)
        if payload is None:
            raise UsageError(f"context route has unknown payload range: {range_id}")
        raw, segment = _baseline_segment(root, commit, payload)
        raw_segments.append(raw)
        segments.append(segment)
        disk_reads.append(f"{payload.path}:{payload.start_line}-{payload.end_line}")
    return PayloadResolution(
        "temporary-ranges-until-materialized",
        "baseline-ranges",
        tuple(raw_segments),
        tuple(segments),
        tuple(disk_reads),
    )

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from model_check_context_baseline import canonical_context_baseline, canonical_json_bytes
from model_check_contract import JsonValue


HEX64_RE = re.compile(r"^[0-9a-f]{64}\n$")


@dataclass(frozen=True, slots=True)
class ContextBaselineFinding:
    code: str
    path: str
    message: str


def _finding(code: str, path: str, message: str) -> ContextBaselineFinding:
    return ContextBaselineFinding(code=code, path=path, message=message)


def _load_baseline(raw: bytes) -> tuple[dict[str, JsonValue] | None, list[ContextBaselineFinding]]:
    findings: list[ContextBaselineFinding] = []
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        findings.append(_finding("baseline-final-lf", "$", "baseline JSON must have exactly one final LF"))
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, [*findings, _finding("baseline-json", "$", str(error))]
    if not isinstance(value, dict):
        return None, [*findings, _finding("baseline-json", "$", "baseline root must be an object")]
    if canonical_json_bytes(value) != raw:
        findings.append(_finding("baseline-canonical-json", "$", "baseline JSON is not canonical"))
    return value, findings


def _validate_digest(raw: bytes, digest_raw: bytes) -> list[ContextBaselineFinding]:
    try:
        digest_text = digest_raw.decode("ascii")
    except UnicodeDecodeError as error:
        return [_finding("digest-format", "tests/fixtures/model-context-baseline.sha256", str(error))]
    if not HEX64_RE.match(digest_text):
        return [
            _finding(
                "digest-format",
                "tests/fixtures/model-context-baseline.sha256",
                "digest must be lowercase 64-hex plus LF",
            )
        ]
    expected = hashlib.sha256(raw).hexdigest() + "\n"
    if digest_text != expected:
        return [
            _finding(
                "digest-mismatch",
                "tests/fixtures/model-context-baseline.sha256",
                "digest does not match raw baseline JSON bytes",
            )
        ]
    return []


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _validate_sets(
    baseline: dict[str, JsonValue],
    expected: dict[str, JsonValue],
) -> list[ContextBaselineFinding]:
    findings: list[ContextBaselineFinding] = []
    scenarios = baseline.get("scenarios", [])
    expected_scenarios = expected.get("scenarios", [])
    if not isinstance(scenarios, list) or not isinstance(expected_scenarios, list):
        return [_finding("scenario-shape", "$.scenarios", "scenarios must be arrays")]
    ids = [str(row.get("id")) for row in scenarios if isinstance(row, dict)]
    terminals = [str(row.get("terminal")) for row in scenarios if isinstance(row, dict)]
    expected_ids = [str(row["id"]) for row in expected_scenarios if isinstance(row, dict)]
    expected_terminals = [str(row["terminal"]) for row in expected_scenarios if isinstance(row, dict)]
    if ids != sorted(ids):
        findings.append(_finding("scenario-order", "$.scenarios", "scenarios must be sorted by ID"))
    if set(ids) != set(expected_ids) or _duplicates(ids):
        findings.append(_finding("scenario-set", "$.scenarios", "scenario IDs differ from route graph"))
    if set(terminals) != set(expected_terminals) or _duplicates(terminals):
        findings.append(_finding("terminal-set", "$.scenarios", "terminals differ from route graph"))
    return findings


def _validate_segments(baseline: dict[str, JsonValue]) -> list[ContextBaselineFinding]:
    findings: list[ContextBaselineFinding] = []
    for scenario in baseline.get("scenarios", []):
        if not isinstance(scenario, dict):
            continue
        scenario_id = str(scenario.get("id"))
        segments = scenario.get("segments", [])
        if not isinstance(segments, list):
            continue
        ordinals = [segment.get("ordinal") for segment in segments if isinstance(segment, dict)]
        if ordinals != list(range(len(segments))) or _duplicates([str(item) for item in ordinals]):
            findings.append(_finding("segment-ordinal", f"$.scenarios[{scenario_id}].segments", "segment ordinals must be contiguous from zero"))
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                continue
            path = str(segment.get("path", ""))
            content = str(segment.get("content", ""))
            encoded = content.encode("utf-8")
            if path.startswith("/") or "\\" in path:
                findings.append(_finding("segment-path", f"$.scenarios[{scenario_id}].segments[{index}].path", "segment path must be repository-relative POSIX"))
            if segment.get("sha256") != hashlib.sha256(encoded).hexdigest():
                findings.append(_finding("segment-sha256", f"$.scenarios[{scenario_id}].segments[{index}].sha256", "segment hash does not match UTF-8 content"))
    return findings


def _validate_loading(baseline: dict[str, JsonValue]) -> list[ContextBaselineFinding]:
    findings: list[ContextBaselineFinding] = []
    budgets = baseline["budgets"]
    startup = budgets["startup"]
    startup_segments = startup["segments"]
    startup_paths = [str(segment["path"]) for segment in startup_segments if isinstance(segment, dict)]
    startup_ids = [str(segment["id"]) for segment in startup_segments if isinstance(segment, dict)]
    if startup_ids.count("runtime.project-agents.injected") != 1:
        findings.append(_finding("runtime-agents-count", "$.budgets.startup.segments", "runtime AGENTS must be injected exactly once"))
    if "model/BRAIN.common.md" in startup_paths:
        findings.append(_finding("brain-eager", "$.budgets.startup.segments", "BRAIN must remain conditional"))
    if int(startup["current_bytes"]) > int(startup["cap_bytes"]):
        findings.append(_finding("startup-budget", "$.budgets.startup.current_bytes", "startup exceeds 75% baseline cap"))
    conditional = budgets["conditional_scenarios"]
    if isinstance(conditional, dict):
        for scenario_id, budget in conditional.items():
            if isinstance(budget, dict) and int(budget["current_bytes"]) > int(budget["cap_bytes"]):
                findings.append(_finding("conditional-budget", f"$.budgets.conditional_scenarios.{scenario_id}", "conditional scenario exceeds 110% baseline cap"))
    return findings


def _validate_terminal_loading(baseline: dict[str, JsonValue]) -> list[ContextBaselineFinding]:
    findings: list[ContextBaselineFinding] = []
    for scenario in baseline.get("scenarios", []):
        if not isinstance(scenario, dict):
            continue
        scenario_id = str(scenario.get("id"))
        if scenario.get("terminal_load_count") != 1:
            findings.append(_finding("terminal-load-count", f"$.scenarios[{scenario_id}].terminal_load_count", "exactly one terminal must load"))
        if any(
            isinstance(segment, dict)
            and segment.get("path") == "model/BRAIN.common.md"
            and scenario.get("id") != "scenario.brain-structure"
            for segment in scenario.get("segments", [])
        ):
            findings.append(_finding("broad-body-inclusion", f"$.scenarios[{scenario_id}].segments", "scenario includes unrelated BRAIN body"))
    return findings


def validate_context_baseline(
    root: Path,
    model: dict[str, JsonValue],
    baseline_raw: bytes,
    digest_raw: bytes,
) -> list[ContextBaselineFinding]:
    baseline, findings = _load_baseline(baseline_raw)
    findings.extend(_validate_digest(baseline_raw, digest_raw))
    if baseline is None:
        return findings
    expected = canonical_context_baseline(root, model)
    findings.extend(_validate_sets(baseline, expected))
    findings.extend(_validate_segments(baseline))
    findings.extend(_validate_loading(baseline))
    findings.extend(_validate_terminal_loading(baseline))
    if baseline != expected:
        findings.append(_finding("baseline-derived-mismatch", "$", "baseline differs from executable route harness"))
    return findings

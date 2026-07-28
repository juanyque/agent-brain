from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from model_check_contract import CodeDef, Finding, JsonValue


CLAIM_KEY = "task12_recurring_job_relocation_claims"
EXPECTED_CLUSTERS = frozenset(
    {
        "cluster.jobs.weekly-stale-wip-review",
        "cluster.jobs.weekly-trash-review",
        "cluster.jobs.monthly-maintenance-rule-refinement",
        "cluster.jobs.yearly-journal-classification",
    }
)


@dataclass(frozen=True, slots=True)
class EvidenceRange:
    path: str
    start_line: int
    end_line: int
    sha256: str


def _json_object(path: Path) -> dict[str, JsonValue]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _line_range(path: Path, start_line: int, end_line: int) -> bytes | None:
    try:
        lines = path.read_bytes().splitlines(keepends=True)
    except OSError:
        return None
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        return None
    return b"".join(lines[start_line - 1 : end_line])


def _bytes_line_range(raw: bytes, start_line: int, end_line: int) -> bytes | None:
    lines = raw.splitlines(keepends=True)
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        return None
    return b"".join(lines[start_line - 1 : end_line])


def _range(value: JsonValue) -> EvidenceRange | None:
    match value:
        case {
            "path": str(path),
            "start_line": int(start_line),
            "end_line": int(end_line),
            "sha256": str(digest),
        }:
            return EvidenceRange(path, start_line, end_line, digest)
        case _:
            return None


def _finding(code: CodeDef, path: str, target: str, message: str) -> Finding:
    return Finding(
        code=code.code,
        family=code.family,
        severity=code.severity,
        path=path,
        target=target,
        message=message,
    )


def _claims(ledger: dict[str, JsonValue]) -> dict[str, dict[str, JsonValue]]:
    raw_claims = ledger.get(CLAIM_KEY, [])
    if not isinstance(raw_claims, list):
        return {}
    claims: dict[str, dict[str, JsonValue]] = {}
    for row in raw_claims:
        match row:
            case {"cluster_id": str(cluster_id)} if isinstance(row, dict):
                claims[cluster_id] = row
            case _:
                continue
    return claims


def _baseline_file(root: Path, commit: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _validate_source(
    root: Path,
    code: CodeDef,
    baseline_commit: str,
    cluster_id: str,
    source_value: JsonValue,
) -> Finding | None:
    source = _range(source_value)
    if source is None or source.path != "model/JOBS.common.md":
        return _finding(code, "docs/migrations/2026-07-operating-model-ledger.json", cluster_id, "task12 source range is malformed")
    raw_file = _baseline_file(root, baseline_commit, source.path)
    if raw_file is None:
        return _finding(code, source.path, cluster_id, "task12 baseline source cannot be read")
    raw_range = _bytes_line_range(raw_file, source.start_line, source.end_line)
    if raw_range is None:
        return _finding(code, source.path, cluster_id, "task12 source range cannot be read")
    if hashlib.sha256(raw_range).hexdigest() != source.sha256:
        return _finding(code, source.path, cluster_id, "task12 source range hash changed")
    return None


def _validate_destination(
    root: Path,
    code: CodeDef,
    cluster_id: str,
    destination_value: JsonValue,
) -> Finding | None:
    destination = _range(destination_value)
    if destination is None:
        return _finding(code, "docs/migrations/2026-07-operating-model-ledger.json", cluster_id, "task12 destination range is malformed")
    raw_range = _line_range(root / destination.path, destination.start_line, destination.end_line)
    if raw_range is None:
        return _finding(code, destination.path, cluster_id, "task12 destination range cannot be read")
    if hashlib.sha256(raw_range).hexdigest() != destination.sha256:
        return _finding(code, destination.path, cluster_id, "task12 destination range hash changed")
    return None


def task12_ledger_findings(root: Path, ledger_path: Path, code: CodeDef) -> list[Finding]:
    ledger = _json_object(ledger_path)
    claims = _claims(ledger)
    if code.code == "missing-relocation-claim":
        return [
            _finding(code, ledger_path.relative_to(root).as_posix(), cluster_id, "task12 recurring job relocation claim is missing")
            for cluster_id in sorted(EXPECTED_CLUSTERS - set(claims))
        ]
    baseline_commit = ledger.get("baseline_commit")
    if not isinstance(baseline_commit, str):
        return [_finding(code, ledger_path.relative_to(root).as_posix(), CLAIM_KEY, "task12 baseline commit is missing")]
    findings: list[Finding] = []
    for cluster_id in sorted(EXPECTED_CLUSTERS):
        claim = claims.get(cluster_id)
        if claim is None:
            continue
        if claim.get("status") != "relocated-task-12-remediation-1":
            findings.append(_finding(code, ledger_path.relative_to(root).as_posix(), cluster_id, "task12 relocation status is missing"))
            continue
        source_finding = _validate_source(root, code, baseline_commit, cluster_id, claim.get("source"))
        if source_finding is not None:
            findings.append(source_finding)
        destination_finding = _validate_destination(root, code, cluster_id, claim.get("destination"))
        if destination_finding is not None:
            findings.append(destination_finding)
    return sorted(findings, key=lambda item: (item.path, item.target, item.message))

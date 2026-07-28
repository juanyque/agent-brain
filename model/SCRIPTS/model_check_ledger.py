from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from model_check_contract import CodeDef, Finding, JsonValue


@dataclass(frozen=True, slots=True)
class DestinationRange:
    path: str
    heading: str
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


def _heading_range(path: Path, heading: str) -> tuple[int, int] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    headings = [
        (line.removeprefix("## "), index)
        for index, line in enumerate(lines, start=1)
        if line.startswith("## ")
    ]
    for index, (current, start_line) in enumerate(headings):
        if current != heading:
            continue
        end_line = headings[index + 1][1] - 1 if index + 1 < len(headings) else len(lines)
        return start_line, end_line
    return None


def _destination_range(value: JsonValue) -> DestinationRange | None:
    match value:
        case {
            "path": str(path),
            "heading": str(heading),
            "start_line": int(start_line),
            "end_line": int(end_line),
            "sha256": str(digest),
        }:
            return DestinationRange(
                path=path,
                heading=heading,
                start_line=start_line,
                end_line=end_line,
                sha256=digest,
            )
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


def _trim_claims(ledger: dict[str, JsonValue]) -> dict[str, dict[str, JsonValue]]:
    raw_claims = ledger.get("task7_trim_claims", [])
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


def _relocation_claims(ledger: dict[str, JsonValue]) -> tuple[dict[str, JsonValue], ...]:
    raw_claims = ledger.get("relocation_claims", [])
    if not isinstance(raw_claims, list):
        return ()
    return tuple(row for row in raw_claims if isinstance(row, dict))


def _validate_destination(
    root: Path,
    code: CodeDef,
    cluster_id: str,
    destination: DestinationRange,
) -> Finding | None:
    if destination.sha256 == "0" * 64:
        return _finding(code, destination.path, cluster_id, "task7 destination hash is zero")
    heading = _heading_range(root / destination.path, destination.heading)
    if (
        heading is None
        or destination.start_line < heading[0]
        or destination.end_line > heading[1]
    ):
        return _finding(code, destination.path, cluster_id, "task7 destination heading range is missing or changed")
    raw = _line_range(root / destination.path, destination.start_line, destination.end_line)
    if raw is None:
        return _finding(code, destination.path, cluster_id, "task7 destination range cannot be read")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != destination.sha256:
        return _finding(code, destination.path, cluster_id, "task7 destination range hash changed")
    return None


def _validate_trim_claim(
    code: CodeDef,
    cluster_id: str,
    trim_claim: dict[str, JsonValue] | None,
    relocation: dict[str, JsonValue],
    destination: DestinationRange,
    raw: bytes,
) -> Finding | None:
    if trim_claim is None:
        return _finding(code, destination.path, cluster_id, "task7 trim claim is missing")
    if trim_claim.get("destination_sha256") != destination.sha256:
        return _finding(code, destination.path, cluster_id, "task7 trim destination hash disagrees")
    if trim_claim.get("removed_bytes") != len(raw):
        return _finding(code, destination.path, cluster_id, "task7 trim byte count disagrees")
    if trim_claim.get("removed_source_ranges") != relocation.get("source_ranges"):
        return _finding(code, destination.path, cluster_id, "task7 trim source ranges disagree")
    if relocation.get("trim_status") != "source-trimmed-task-7":
        return _finding(code, destination.path, cluster_id, "task7 relocation trim status is missing")
    evidence = relocation.get("removed_source_evidence")
    if not isinstance(evidence, list) or not evidence:
        return _finding(code, destination.path, cluster_id, "task7 removed source evidence is missing")
    return None


def task7_ledger_findings(root: Path, ledger_path: Path, code: CodeDef) -> list[Finding]:
    ledger = _json_object(ledger_path)
    trim_claims = _trim_claims(ledger)
    findings: list[Finding] = []
    for relocation in _relocation_claims(ledger):
        if relocation.get("destination") != "AGENTS.md":
            continue
        cluster_id = relocation.get("cluster_id")
        if not isinstance(cluster_id, str):
            continue
        trim_claim = trim_claims.get(cluster_id)
        if trim_claim is None:
            continue
        destination = _destination_range(relocation.get("copied_destination"))
        if destination is None:
            findings.append(_finding(code, "AGENTS.md", cluster_id, "task7 destination range is malformed"))
            continue
        finding = _validate_destination(root, code, cluster_id, destination)
        if finding is not None:
            findings.append(finding)
            continue
        raw = _line_range(root / destination.path, destination.start_line, destination.end_line)
        if raw is None:
            findings.append(_finding(code, destination.path, cluster_id, "task7 destination range cannot be read"))
            continue
        finding = _validate_trim_claim(code, cluster_id, trim_claim, relocation, destination, raw)
        if finding is not None:
            findings.append(finding)
    return sorted(findings, key=lambda item: (item.path, item.target, item.message))

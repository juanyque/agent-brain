#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from model_check_contract import Finding, JsonValue, sorted_findings
from model_check_render import stable_json


SCHEMA_VERSION: Final = "agent-brain-evidence-ownership/v1"
OWNER_PATH: Final = "model/RULES-REVIEW-EVIDENCE.common.md"
ARCHIVE_DESTINATION: Final = "ARCHIVED/Reviews/"
REPORT_TEMPLATES: Final = (
    "model/TEMPLATES/TEMPLATE.brag-report.common.md",
    "model/TEMPLATES/TEMPLATE.feedback-report.common.md",
    "model/TEMPLATES/TEMPLATE.complaint-report.common.md",
)
SCAN_PATHS: Final = (
    OWNER_PATH,
    "model/TASK_TYPES/evidence-management.common.md",
    "model/TASK_TYPES/brag-report.common.md",
    "model/TASK_TYPES/feedback-report.common.md",
    "model/TASK_TYPES/complaint-report.common.md",
    *REPORT_TEMPLATES,
    "model/TEMPLATES/TEMPLATE.evidence-note.common.md",
)


@dataclass(frozen=True, slots=True)
class OwnershipBlock:
    path: str
    line: int
    value: dict[str, JsonValue]


def _finding(code: str, family: str, path: str, target: str, message: str) -> Finding:
    return Finding(code, family, "error", path, target, message)


def _json_object(raw: str, path: str, line: int) -> dict[str, JsonValue] | Finding:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        return _finding(
            "malformed-evidence-ownership-contract",
            "evidence-ownership",
            path,
            f"line {line}",
            f"ownership JSON is malformed: {error.msg}",
        )
    match value:
        case dict():
            return value
        case _:
            return _finding(
                "malformed-evidence-ownership-contract",
                "evidence-ownership",
                path,
                f"line {line}",
                "ownership metadata must be a JSON object",
            )


def ownership_blocks(root: Path) -> tuple[tuple[OwnershipBlock, ...], tuple[Finding, ...]]:
    blocks: list[OwnershipBlock] = []
    findings: list[Finding] = []
    for rel_path in SCAN_PATHS:
        path = root / rel_path
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if line.strip() != "```json evidence-ownership":
                continue
            body: list[str] = []
            for body_line in lines[index + 1 :]:
                if body_line.strip() == "```":
                    parsed = _json_object("\n".join(body), rel_path, index + 1)
                    match parsed:
                        case Finding():
                            findings.append(parsed)
                        case dict() as value:
                            blocks.append(OwnershipBlock(path=rel_path, line=index + 1, value=value))
                    break
                body.append(body_line)
            else:
                findings.append(
                    _finding(
                        "malformed-evidence-ownership-contract",
                        "evidence-ownership",
                        rel_path,
                        f"line {index + 1}",
                        "ownership JSON fence is not closed",
                    )
                )
    return tuple(blocks), tuple(findings)


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return values
        if ":" not in line:
            continue
        key, value = line.split(":", maxsplit=1)
        values[key.strip()] = value.strip()
    return values


def _allowed_statuses(row: JsonValue) -> tuple[str, ...] | None:
    match row:
        case {"allowed_statuses": list(values)} if all(isinstance(value, str) for value in values):
            return tuple(values)
        case _:
            return None


def _status_findings(root: Path, block: OwnershipBlock) -> list[Finding]:
    match block.value:
        case {"reports": {"types": dict(report_types)}}:
            pass
        case {"reports": dict()}:
            return [
                _finding(
                    "malformed-evidence-ownership-contract",
                    "evidence-ownership",
                    block.path,
                    "reports.types",
                    "owner metadata must declare report types",
                )
            ]
        case _:
            return [
                _finding(
                    "malformed-evidence-ownership-contract",
                    "evidence-ownership",
                    block.path,
                    "reports",
                    "owner metadata must declare reports",
                )
            ]
    findings: list[Finding] = []
    for template in REPORT_TEMPLATES:
        kind = template.removeprefix("model/TEMPLATES/TEMPLATE.").removesuffix("-report.common.md")
        row = report_types.get(kind)
        statuses = _allowed_statuses(row)
        if statuses is None:
            findings.append(
                _finding(
                    "malformed-evidence-ownership-contract",
                    "evidence-ownership",
                    block.path,
                    kind,
                    "report type must declare allowed_statuses",
                )
            )
            continue
        status = frontmatter(root / template).get("status", "")
        if status not in statuses:
            findings.append(
                _finding(
                    "unknown-review-status",
                    "review-status",
                    template,
                    status,
                    "template initial status is not allowed by review evidence owner",
                )
            )
    return findings


def _owner_findings(blocks: tuple[OwnershipBlock, ...]) -> list[Finding]:
    if not blocks:
        return [
            _finding(
                "missing-evidence-owner",
                "evidence-ownership",
                OWNER_PATH,
                SCHEMA_VERSION,
                "review evidence lifecycle owner metadata is missing",
            )
        ]
    if len(blocks) > 1:
        block = blocks[0]
        return [
            _finding(
                "duplicate-policy-owner",
                "evidence-ownership",
                block.path,
                f"line {block.line}",
                "review evidence lifecycle has more than one owner metadata block",
            )
        ]
    return []


def _contract_findings(root: Path, block: OwnershipBlock) -> list[Finding]:
    findings: list[Finding] = []
    if block.path != OWNER_PATH:
        findings.append(
            _finding(
                "duplicate-policy-owner",
                "evidence-ownership",
                block.path,
                f"line {block.line}",
                "review evidence lifecycle owner must be RULES-REVIEW-EVIDENCE",
            )
        )
    if block.value.get("schema_version") != SCHEMA_VERSION:
        findings.append(
            _finding(
                "malformed-evidence-ownership-contract",
                "evidence-ownership",
                block.path,
                "schema_version",
                "review evidence ownership schema is unknown",
            )
        )
    match block.value:
        case {"reports": dict(reports)}:
            destination = reports.get("archive_destination")
        case _:
            destination = None
    if destination != ARCHIVE_DESTINATION:
        findings.append(
            _finding(
                "review-archive-destination",
                "review-archive",
                block.path,
                str(destination),
                "review reports must archive under ARCHIVED/Reviews/",
            )
        )
    findings.extend(_status_findings(root, block))
    return findings


def scan_evidence_ownership(root: Path) -> list[Finding]:
    blocks, malformed = ownership_blocks(root)
    if malformed:
        return sorted_findings(list(malformed))
    findings: list[Finding] = []
    owner_findings = _owner_findings(blocks)
    findings.extend(owner_findings)
    if owner_findings:
        return sorted_findings(findings)
    findings.extend(_contract_findings(root, blocks[0]))
    return sorted_findings(findings)


def parse_args(argv: list[str]) -> tuple[Path, bool]:
    parser = argparse.ArgumentParser(description="Read-only review evidence ownership checker")
    parser.add_argument("--root", default=".")
    parser.add_argument("--strict", action="store_true")
    namespace = parser.parse_args(argv)
    return Path(namespace.root).expanduser().resolve(), namespace.strict


def run(argv: list[str]) -> tuple[int, str]:
    root, strict = parse_args(argv)
    findings = scan_evidence_ownership(root)
    exit_code = 1 if strict and any(finding.severity == "error" for finding in findings) else 0
    report = {"findings": [finding.as_json() for finding in findings], "source_digest": "task-local"}
    return exit_code, stable_json(report) + "\n"


def main() -> int:
    exit_code, output = run(sys.argv[1:])
    sys.stdout.write(output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# --- How to run ---
# python3 model/SCRIPTS/model_check_session_ownership.py --root . --format json
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from model_check_contract import Finding, JsonValue


FAMILY: Final = "session-ownership"


@dataclass(frozen=True, slots=True)
class OwnershipRow:
    policy_area: str
    owner: str
    authority: str


@dataclass(frozen=True, slots=True)
class ExpectedRow:
    path: str
    policy_area: str
    owner: str
    authority: str


@dataclass(frozen=True, slots=True)
class FindingContext:
    code: str
    path: str
    target: str


@dataclass(frozen=True, slots=True)
class ParsedOwnership:
    rows: dict[str, OwnershipRow]
    findings: tuple[Finding, ...]


SESSION_RULES: Final = "model/RULES-SESSION-LIFECYCLE.common.md"
DAILY_RULES: Final = "model/RULES-DAILY-NOTES.common.md"
JOBS: Final = "model/JOBS.common.md"
SKILL: Final = "skills/brain/SKILL.md"

EXPECTED_ROWS: Final = tuple(
    ExpectedRow(*row)
    for row in (
        (SESSION_RULES, "state-transitions", "RULES-SESSION-LIFECYCLE.common.md", "canonical"),
        (SESSION_RULES, "multi-session-coordination", "RULES-SESSION-LIFECYCLE.common.md", "canonical"),
        (SESSION_RULES, "canonical-open-authority", "session_open.py", "unique"),
        (SESSION_RULES, "compatibility-fallback", "session_bootstrap.py", "compatibility-only"),
        (SESSION_RULES, "git-operations", "user", "explicit-authorization-required"),
        (DAILY_RULES, "daily-shape-semantics", "RULES-DAILY-NOTES.common.md", "canonical"),
        (DAILY_RULES, "cleanup-eligibility", "RULES-DAILY-NOTES.common.md", "canonical"),
        (DAILY_RULES, "todo-carryover-semantics", "RULES-DAILY-NOTES.common.md", "canonical"),
        (DAILY_RULES, "session-registration", "session_open.py", "idempotent-upsert-authority"),
        (JOBS, "job-shape", "JOBS.common.md", "purpose-trigger-schedule-links-only"),
        (JOBS, "procedure-source", "RULES-SESSION-LIFECYCLE.common.md", "linked-not-duplicated"),
        (JOBS, "daily-semantics-source", "RULES-DAILY-NOTES.common.md", "linked-not-duplicated"),
        (JOBS, "git-operations", "user", "explicit-authorization-required"),
        (SKILL, "canonical-open-authority", "session_open.py", "unique"),
        (SKILL, "compatibility-fallback", "session_bootstrap.py", "compatibility-only"),
    )
)


def _finding(context: FindingContext, message: str) -> Finding:
    return Finding(
        code=context.code,
        family=FAMILY,
        severity="error",
        path=context.path,
        target=context.target,
        message=message,
    )


def _cells(line: str) -> tuple[str, ...]:
    return tuple(cell.strip() for cell in line.strip().strip("|").split("|"))


def _ownership_block(text: str) -> tuple[str, ...] | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line not in {"## Ownership metadata", "### Ownership metadata"}:
            continue
        level = len(line) - len(line.lstrip("#"))
        end = next(
            (
                cursor
                for cursor in range(index + 1, len(lines))
                if lines[cursor].startswith("#")
                and len(lines[cursor]) - len(lines[cursor].lstrip("#")) <= level
            ),
            len(lines),
        )
        return tuple(lines[index + 1 : end])
    return None


def _parse_ownership(path: str, text: str) -> ParsedOwnership:
    block = _ownership_block(text)
    if block is None:
        return ParsedOwnership(
            rows={},
            findings=(
                _finding(
                    FindingContext(
                        code="missing-ownership-metadata",
                        path=path,
                        target="Ownership metadata",
                    ),
                    "document has no ownership metadata section",
                ),
            ),
        )
    table = tuple(line for line in block if line.startswith("|"))
    if len(table) < 3 or _cells(table[0]) != ("Policy area", "Owner", "Authority"):
        return ParsedOwnership(
            rows={},
            findings=(
                _finding(
                    FindingContext(
                        code="malformed-ownership-metadata",
                        path=path,
                        target="Ownership metadata",
                    ),
                    "ownership metadata table header is not parseable",
                ),
            ),
        )
    rows: dict[str, OwnershipRow] = {}
    findings: list[Finding] = []
    for line in table[2:]:
        cells = _cells(line)
        if len(cells) != 3:
            findings.append(
                _finding(
                    FindingContext(
                        code="malformed-ownership-metadata",
                        path=path,
                        target="Ownership metadata",
                    ),
                    "ownership metadata row is not a three-column table row",
                )
            )
            continue
        rows[cells[0]] = OwnershipRow(
            policy_area=cells[0],
            owner=cells[1],
            authority=cells[2],
        )
    return ParsedOwnership(rows=rows, findings=tuple(findings))


def _check_expected_rows(root: Path) -> list[Finding]:
    grouped: dict[str, tuple[ExpectedRow, ...]] = {}
    for row in EXPECTED_ROWS:
        grouped[row.path] = (*grouped.get(row.path, ()), row)
    findings: list[Finding] = []
    for path, expected_rows in grouped.items():
        document = root / path
        parsed = _parse_ownership(path, document.read_text(encoding="utf-8"))
        findings.extend(parsed.findings)
        if parsed.findings:
            continue
        for expected in expected_rows:
            actual = parsed.rows.get(expected.policy_area)
            if actual is None:
                findings.append(
                    _finding(
                        FindingContext(
                            code="missing-ownership-row",
                            path=path,
                            target=expected.policy_area,
                        ),
                        "required ownership row is missing",
                    )
                )
                continue
            if actual.owner == expected.owner and actual.authority == expected.authority:
                continue
            code = "stale-open-authority"
            if expected.policy_area != "canonical-open-authority":
                code = "stale-ownership-authority"
            findings.append(
                _finding(
                    FindingContext(
                        code=code,
                        path=path,
                        target=expected.policy_area,
                    ),
                    f"expected {expected.owner} / {expected.authority}; found {actual.owner} / {actual.authority}",
                )
            )
    return findings


def _check_jobs_shape(root: Path) -> list[Finding]:
    path = "model/JOBS.common.md"
    text = (root / path).read_text(encoding="utf-8")
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line == "### Tasks":
            findings.append(
                _finding(
                    FindingContext(
                        code="jobs-flow-checklist",
                        path=path,
                        target=f"line:{line_number}",
                    ),
                    "JOBS.common.md must link procedures instead of carrying task checklists",
                )
            )
        if "Run the Flow " in line and "checklist" in line:
            findings.append(
                _finding(
                    FindingContext(
                        code="jobs-flow-checklist",
                        path=path,
                        target=f"line:{line_number}",
                    ),
                    "JOBS.common.md must not duplicate session lifecycle flow checklists",
                )
            )
    return findings


def session_ownership_findings(root: Path) -> list[Finding]:
    findings = [*_check_expected_rows(root), *_check_jobs_shape(root)]
    return sorted(findings, key=lambda item: (item.code, item.path, item.target))


def _json_report(findings: list[Finding]) -> dict[str, JsonValue]:
    return {"findings": [finding.as_json() for finding in findings]}


def run(argv: list[str]) -> tuple[int, str]:
    parser = argparse.ArgumentParser(description="Session ownership checker")
    parser.add_argument("--root", default=".")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    findings = session_ownership_findings(Path(args.root).expanduser().resolve())
    if args.format == "json":
        return (1 if findings else 0), json.dumps(_json_report(findings), sort_keys=True) + "\n"
    lines = [
        f"{finding.severity}\t{finding.code}\t{finding.path}\t{finding.target}\t{finding.message}"
        for finding in findings
    ]
    return (1 if findings else 0), "\n".join(lines) + ("\n" if lines else "")


def main() -> int:
    exit_code, output = run(sys.argv[1:])
    sys.stdout.write(output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

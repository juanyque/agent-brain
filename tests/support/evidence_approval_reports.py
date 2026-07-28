from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from evidence_closure_records import file_ref, pin_json, verify_json_ref
from evidence_json import (
    ContractError,
    JsonValue,
    canonical_bytes,
    create_json,
)

TOOLING_REPORT_SCHEMA = "agent-brain-tooling-review-report/v1"
TOOLING_SUMMARY_SCHEMA = "agent-brain-tooling-review-summary/v1"
GATE_REPORT_SCHEMA = "agent-brain-independent-gate-report/v1"
GATE_SUMMARY_SCHEMA = "agent-brain-independent-gate-summary/v1"

REPORT_KEYS = {
    "blockers",
    "executor_id",
    "findings",
    "git_state_sha256",
    "governed_runs_sha256",
    "plan_sha256",
    "product_sha256",
    "reviewer_id",
    "role",
    "schema_version",
    "task_receipts_sha256",
    "verdict",
}
SUMMARY_KEYS = REPORT_KEYS | {"created_at", "report", "report_schema_version"}


@dataclass(frozen=True, slots=True)
class ReportContract:
    role: str
    report_schema: str
    summary_schema: str
    verdict: str


@dataclass(frozen=True, slots=True)
class ReportBindings:
    git_state_sha256: str
    governed_runs_sha256: str
    plan_sha256: str
    product_sha256: str
    task_receipts_sha256: str


TOOLING_CONTRACT = ReportContract(
    role="tooling-review",
    report_schema=TOOLING_REPORT_SCHEMA,
    summary_schema=TOOLING_SUMMARY_SCHEMA,
    verdict="APPROVE",
)
GATE_CONTRACT = ReportContract(
    role="independent-gate-report",
    report_schema=GATE_REPORT_SCHEMA,
    summary_schema=GATE_SUMMARY_SCHEMA,
    verdict="CONFIRMED",
)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_report_summary(
    report_path: Path,
    output_path: Path,
    contract: ReportContract,
    bindings: ReportBindings,
) -> None:
    report = _load_report(report_path, contract, bindings)
    summary = {
        "blockers": report["blockers"],
        "created_at": _now(),
        "executor_id": report["executor_id"],
        "findings": report["findings"],
        "git_state_sha256": report["git_state_sha256"],
        "governed_runs_sha256": report["governed_runs_sha256"],
        "plan_sha256": report["plan_sha256"],
        "product_sha256": report["product_sha256"],
        "report": file_ref(report_path),
        "report_schema_version": contract.report_schema,
        "reviewer_id": report["reviewer_id"],
        "role": report["role"],
        "schema_version": contract.summary_schema,
        "task_receipts_sha256": report["task_receipts_sha256"],
        "verdict": report["verdict"],
    }
    create_json(output_path, summary)


def verify_report_summary(
    summary_path: Path,
    contract: ReportContract,
    bindings: ReportBindings,
    value: dict[str, JsonValue] | None = None,
    data: bytes | None = None,
) -> None:
    if value is None or data is None:
        pinned = pin_json(summary_path)
        if value is None:
            value = pinned.value
        if data is None:
            data = pinned.data
    _expect_summary(data, value, contract, bindings)
    report = verify_json_ref(value["report"])
    if report.data != canonical_bytes(report.value):
        raise ContractError("approval report is not canonical")
    _expect_report(report.value, contract, bindings)
    for key in REPORT_KEYS - {"schema_version"}:
        if value.get(key) != report.value.get(key):
            raise ContractError("approval report summary does not match report")


def _load_report(
    report_path: Path,
    contract: ReportContract,
    bindings: ReportBindings,
) -> dict[str, JsonValue]:
    report = pin_json(report_path)
    if report.data != canonical_bytes(report.value):
        raise ContractError("approval report is not canonical")
    _expect_report(report.value, contract, bindings)
    return report.value


def _expect_report(
    report: dict[str, JsonValue],
    contract: ReportContract,
    bindings: ReportBindings,
) -> None:
    if set(report) != REPORT_KEYS:
        raise ContractError("invalid approval report schema")
    if report["schema_version"] != contract.report_schema or report["role"] != contract.role:
        raise ContractError("approval report schema/role mismatch")
    if report["verdict"] != contract.verdict:
        raise ContractError("approval report verdict mismatch")
    _expect_empty(report["findings"], "findings")
    _expect_empty(report["blockers"], "blockers")
    _expect_reviewer_separation(report)
    _expect_bindings(report, bindings)


def _expect_summary(
    summary_data: bytes,
    summary: dict[str, JsonValue],
    contract: ReportContract,
    bindings: ReportBindings,
) -> None:
    if set(summary) != SUMMARY_KEYS:
        raise ContractError("invalid approval report summary schema")
    if summary_data != canonical_bytes(summary):
        raise ContractError("approval report summary is not canonical")
    if summary["schema_version"] != contract.summary_schema:
        raise ContractError("approval report summary schema mismatch")
    if summary["report_schema_version"] != contract.report_schema or summary["role"] != contract.role:
        raise ContractError("approval report summary role mismatch")
    if summary["verdict"] != contract.verdict:
        raise ContractError("approval report summary verdict mismatch")
    _expect_empty(summary["findings"], "findings")
    _expect_empty(summary["blockers"], "blockers")
    _expect_reviewer_separation(summary)
    _expect_bindings(summary, bindings)


def _expect_empty(value: JsonValue, name: str) -> None:
    if value != []:
        raise ContractError(f"approval report {name} must be empty")


def _expect_reviewer_separation(value: dict[str, JsonValue]) -> None:
    reviewer = value.get("reviewer_id")
    executor = value.get("executor_id")
    if not isinstance(reviewer, str) or not reviewer:
        raise ContractError("approval report reviewer is missing")
    if not isinstance(executor, str) or not executor:
        raise ContractError("approval report executor is missing")
    if reviewer == executor:
        raise ContractError("approval report reviewer/executor separation failed")


def _expect_bindings(value: dict[str, JsonValue], bindings: ReportBindings) -> None:
    expected = {
        "git_state_sha256": bindings.git_state_sha256,
        "governed_runs_sha256": bindings.governed_runs_sha256,
        "plan_sha256": bindings.plan_sha256,
        "product_sha256": bindings.product_sha256,
        "task_receipts_sha256": bindings.task_receipts_sha256,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise ContractError("approval report binding mismatch")

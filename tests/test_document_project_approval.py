from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "manage-document-projects"
PACKAGE = SKILL / "assets" / "project-types" / "residential-lease"
APPROVER = SKILL / "scripts" / "approve_clauses.py"
DATA = PACKAGE / "examples" / "minimal-project.yaml"

CANDIDATES = (
    "lease.object-and-use@0.1.0",
    "lease.term-and-delivery@0.1.0",
    "lease.rent-and-payment@0.1.1",
    "lease.deposit-and-guarantee@0.1.0",
    "lease.rent-update@0.1.0",
    "lease.conservation-and-works@0.1.0",
    "lease.expenses-and-supplies@0.1.0",
    "lease.assignment-subletting-and-preemption@0.1.0",
    "lease.withdrawal-and-termination@0.1.0",
)


class _ExcludedClause(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    reason_code: str


class _Approval(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    catalog: str
    jurisdiction: str
    approved_clause_versions: tuple[str, ...]
    excluded_clause_versions: tuple[_ExcludedClause, ...]


def _write_request(
    workspace: Path,
    approved: tuple[str, ...] = CANDIDATES,
) -> Path:
    request = workspace / "review.yaml"
    _ = request.write_text(
        yaml.safe_dump(
            {
                "review_version": "0.1.0",
                "project_type": str(PACKAGE / "project-type.yaml"),
                "data": str(DATA),
                "document": "lease",
                "reviewed_on": "2026-07-24",
                "reviewer": {
                    "name": "Profesional jurídico de prueba",
                    "professional_id": "DEMO-REVIEWER",
                    "signer_identity": "legal-reviewer@example.test",
                },
                "approved_clause_versions": list(approved),
                "excluded_clause_versions": [
                    {
                        "id": "lease.notices-and-disputes@0.1.0",
                        "reason_code": "intentionally-excluded",
                    },
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return request


def _run_approver(
    request: Path,
    output: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "--script",
            str(APPROVER),
            str(request),
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_approver_binds_exact_review_decisions_to_package_inputs() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        request = _write_request(workspace)
        output = workspace / "approval.yaml"

        # When
        result = _run_approver(request, output)

        # Then
        assert result.returncode == 0, result.stdout + result.stderr
        approval = _Approval.model_validate(
            yaml.safe_load(output.read_text(encoding="utf-8")),
        )
        assert approval.status == "approved"
        assert approval.catalog == "residential-lease-clauses@0.3.0"
        assert approval.jurisdiction == "es-md-madrid@0.1.0"
        assert approval.approved_clause_versions == CANDIDATES
        assert approval.excluded_clause_versions == (
            _ExcludedClause(
                id="lease.notices-and-disputes@0.1.0",
                reason_code="intentionally-excluded",
            ),
        )


def test_approver_rejects_an_incomplete_review() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        request = _write_request(workspace, CANDIDATES[:-1])
        output = workspace / "approval.yaml"

        # When
        result = _run_approver(request, output)

        # Then
        assert result.returncode != 0
        assert "lease.withdrawal-and-termination@0.1.0" in (
            result.stdout + result.stderr
        )
        assert not output.exists()

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml
from document_governance_fixtures import (
    CANDIDATES,
    CHECKS,
    GovernanceFixtureSpec,
    write_signed_governance,
)
from document_governance_release import run_release
from pydantic import BaseModel, ConfigDict


class _LegalReview(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    approved_clause_versions: tuple[str, ...]
    excluded_clause_versions: tuple[str, ...]


class _GenerationReview(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    resolved_checks: tuple[str, ...]
    valid_until: str | None


class _Selection(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    blocked_clauses: tuple[dict[str, str], ...]
    legal_review: _LegalReview
    generation_review: _GenerationReview


def test_release_renderer_records_complete_governance() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        governance = write_signed_governance(workspace)

        # When
        result, output = run_release(workspace, governance)

        # Then
        assert result.returncode == 0, result.stdout + result.stderr
        selection = _Selection.model_validate(
            yaml.safe_load(
                output.with_suffix(".selection.yaml").read_text(encoding="utf-8"),
            ),
        )
        assert selection.status == "reviewed-for-signature"
        assert selection.blocked_clauses == ()
        assert selection.legal_review == _LegalReview(
            status="approved",
            approved_clause_versions=CANDIDATES,
            excluded_clause_versions=("lease.notices-and-disputes@0.1.0",),
        )
        assert selection.generation_review == _GenerationReview(
            status="passed",
            resolved_checks=CHECKS,
            valid_until="2026-08-23",
        )
        assert output.is_file()


def test_release_renderer_rejects_an_unapproved_candidate() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        governance = write_signed_governance(
            workspace,
            GovernanceFixtureSpec(approved=CANDIDATES[:-1]),
        )

        # When
        result, output = run_release(workspace, governance)

        # Then
        assert result.returncode != 0
        assert "lease.withdrawal-and-termination@0.1.0" in (
            result.stdout + result.stderr
        )
        assert not output.exists()
        assert not output.with_suffix(".md").exists()


def test_release_renderer_rejects_expired_jurisdiction_checks() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        governance = write_signed_governance(
            workspace,
            GovernanceFixtureSpec(checks_valid_until="2026-07-23"),
        )

        # When
        result, output = run_release(workspace, governance)

        # Then
        assert result.returncode != 0
        assert "2026-07-23" in result.stdout + result.stderr
        assert not output.exists()
        assert not output.with_suffix(".selection.yaml").exists()

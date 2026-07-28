from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Literal

import yaml
from document_governance_fixtures import (
    DATA,
    TEMPLATE,
    GovernanceFixtureSpec,
    digest,
    write_signed_governance,
)
from document_governance_release import run_release
from pydantic import BaseModel, ConfigDict


class _InputProvenance(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    template: str
    template_sha256: str
    data: str
    data_sha256: str
    selection: str
    selection_sha256: str
    defaults_profile: str
    defaults_path: str
    defaults_sha256: str
    defaults_override: str | None
    defaults_override_sha256: str | None


class _ProfileProvenance(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    id: Literal["css-pdf-a4"]
    path: str
    sha256: str


class _OutputProvenance(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    markdown: str
    markdown_sha256: str
    pdf: str
    pdf_sha256: str


class _Provenance(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="allow")

    provenance_version: Literal["0.1.0"]
    generated_at: datetime
    document_status: Literal["reviewed-for-signature"]
    inputs: _InputProvenance
    profile: _ProfileProvenance
    outputs: _OutputProvenance


def test_release_accepts_trusted_active_approval_and_records_provenance() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        governance = write_signed_governance(workspace)

        # When
        result, output = run_release(workspace, governance)

        # Then
        assert result.returncode == 0, result.stdout + result.stderr
        provenance = _Provenance.model_validate(
            yaml.safe_load(
                output.with_suffix(".provenance.yaml").read_text(encoding="utf-8"),
            ),
        )
        assert provenance.inputs.template_sha256 == digest(TEMPLATE)
        assert provenance.inputs.data_sha256 == digest(DATA)
        assert provenance.outputs.pdf_sha256 == digest(output)


def test_release_rejects_a_withdrawn_signed_approval() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        governance = write_signed_governance(
            workspace,
            GovernanceFixtureSpec(status="withdrawn"),
        )

        # When
        result, output = run_release(workspace, governance)

        # Then
        assert result.returncode != 0
        assert "withdrawn" in result.stdout + result.stderr
        assert not output.exists()


def test_release_rejects_an_approval_changed_after_signing() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        governance = write_signed_governance(workspace)
        approval = governance[0]
        _ = approval.write_text(
            approval.read_text(encoding="utf-8").replace(
                "DEMO-REVIEWER",
                "ALTERED-REVIEWER",
            ),
            encoding="utf-8",
        )

        # When
        result, output = run_release(workspace, governance)

        # Then
        assert result.returncode != 0
        assert "signature verification failed" in result.stdout + result.stderr
        assert not output.exists()


def test_release_rejects_a_superseded_approval_and_names_replacement() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        governance = write_signed_governance(
            workspace,
            GovernanceFixtureSpec(status="superseded"),
        )

        # When
        result, output = run_release(workspace, governance)

        # Then
        assert result.returncode != 0
        assert "superseded" in result.stdout + result.stderr
        assert "1" * 64 in result.stdout + result.stderr
        assert not output.exists()

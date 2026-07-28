from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Literal

import yaml
from project_defaults import DefaultsResolution
from pydantic import BaseModel, ConfigDict
from selection_inputs import digest


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class InputProvenance(_FrozenModel):
    template: str
    template_sha256: str
    data: str
    data_sha256: str
    selection: str | None
    selection_sha256: str | None
    defaults_profile: str | None
    defaults_path: str | None
    defaults_sha256: str | None
    defaults_override: str | None
    defaults_override_sha256: str | None


class ProfileProvenance(_FrozenModel):
    id: Literal["css-pdf-a4"]
    path: str
    sha256: str


class OutputProvenance(_FrozenModel):
    markdown: str
    markdown_sha256: str
    pdf: str
    pdf_sha256: str


class GovernanceProvenance(_FrozenModel):
    approval_sha256: str
    approval_signature_sha256: str
    approval_ledger_sha256: str
    approval_ledger_signature_sha256: str
    allowed_signers_sha256: str
    jurisdiction_checks_sha256: str


class GeneratedDocumentProvenance(_FrozenModel):
    provenance_version: Literal["0.1.0"]
    generated_at: datetime
    document_status: Literal[
        "draft-not-for-signature",
        "reviewed-for-signature",
    ]
    inputs: InputProvenance
    profile: ProfileProvenance
    outputs: OutputProvenance
    governance: GovernanceProvenance | None


@dataclass(frozen=True, slots=True)
class GovernancePaths:
    approval: Path
    approval_signature: Path
    approval_ledger: Path
    approval_ledger_signature: Path
    allowed_signers: Path
    jurisdiction_checks: Path


@dataclass(frozen=True, slots=True)
class ProvenanceRequest:
    template: Path
    data: Path
    selection: Path | None
    profile: Path
    markdown: Path
    pdf: Path
    document_status: Literal[
        "draft-not-for-signature",
        "reviewed-for-signature",
    ]
    governance: GovernancePaths | None
    defaults: DefaultsResolution | None = None


def build_provenance(request: ProvenanceRequest) -> GeneratedDocumentProvenance:
    governance = (
        None
        if request.governance is None
        else GovernanceProvenance(
            approval_sha256=digest(request.governance.approval),
            approval_signature_sha256=digest(request.governance.approval_signature),
            approval_ledger_sha256=digest(request.governance.approval_ledger),
            approval_ledger_signature_sha256=digest(
                request.governance.approval_ledger_signature,
            ),
            allowed_signers_sha256=digest(request.governance.allowed_signers),
            jurisdiction_checks_sha256=digest(
                request.governance.jurisdiction_checks,
            ),
        )
    )
    return GeneratedDocumentProvenance(
        provenance_version="0.1.0",
        generated_at=datetime.now(UTC),
        document_status=request.document_status,
        inputs=InputProvenance(
            template=str(request.template),
            template_sha256=digest(request.template),
            data=str(request.data),
            data_sha256=digest(request.data),
            selection=str(request.selection) if request.selection is not None else None,
            selection_sha256=(
                digest(request.selection) if request.selection is not None else None
            ),
            defaults_profile=(
                request.defaults.profile if request.defaults is not None else None
            ),
            defaults_path=(
                str(request.defaults.profile_path)
                if request.defaults is not None
                else None
            ),
            defaults_sha256=(
                request.defaults.profile_sha256
                if request.defaults is not None
                else None
            ),
            defaults_override=(
                str(request.defaults.override_path)
                if request.defaults is not None
                and request.defaults.override_path is not None
                else None
            ),
            defaults_override_sha256=(
                request.defaults.override_sha256
                if request.defaults is not None
                else None
            ),
        ),
        profile=ProfileProvenance(
            id="css-pdf-a4",
            path=str(request.profile),
            sha256=digest(request.profile),
        ),
        outputs=OutputProvenance(
            markdown=str(request.markdown),
            markdown_sha256=digest(request.markdown),
            pdf=str(request.pdf),
            pdf_sha256=digest(request.pdf),
        ),
        governance=governance,
    )


def provenance_yaml(provenance: GeneratedDocumentProvenance) -> str:
    return yaml.safe_dump(
        provenance.model_dump(mode="json"),
        allow_unicode=True,
        sort_keys=False,
    )

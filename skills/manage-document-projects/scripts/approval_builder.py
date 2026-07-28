from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import ClassVar, Literal

import yaml
from document_governance import validate_approval
from governance_models import (
    ApprovalProvenance,
    ExcludedClause,
    LegalApproval,
    Reviewer,
)
from pydantic import BaseModel, ConfigDict
from selection_inputs import load_yaml, resolve
from selection_project import SelectionBuildRequest, build_selection


class ReviewRequestFile(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    review_version: Literal["0.1.0"]
    project_type: Path
    data: Path
    document: str
    reviewed_on: date
    reviewer: Reviewer
    approved_clause_versions: tuple[str, ...]
    excluded_clause_versions: tuple[ExcludedClause, ...]


def build_approval(request_path: Path) -> LegalApproval:
    """Bind professional review decisions to exact package input hashes."""
    request = load_yaml(request_path, ReviewRequestFile)
    prepared = build_selection(
        SelectionBuildRequest(
            manifest=resolve(request.project_type, request_path.parent),
            data=resolve(request.data, request_path.parent),
            document=request.document,
        ),
    )
    provenance = prepared.selection.provenance
    approval = LegalApproval(
        approval_version="0.1.0",
        status="approved",
        catalog=prepared.selection.catalog,
        jurisdiction=prepared.selection.jurisdiction,
        reviewed_on=request.reviewed_on,
        reviewer=request.reviewer,
        approved_clause_versions=request.approved_clause_versions,
        excluded_clause_versions=request.excluded_clause_versions,
        provenance=ApprovalProvenance(
            catalog_sha256=provenance.catalog_sha256,
            jurisdiction_sha256=provenance.jurisdiction_sha256,
            legal_source_snapshot_sha256=(
                provenance.legal_source_snapshot_sha256
            ),
        ),
    )
    _ = validate_approval(prepared.selection, approval)
    return approval


def approval_yaml(approval: LegalApproval) -> str:
    """Serialize a legal approval as deterministic YAML."""
    return yaml.safe_dump(
        approval.model_dump(mode="json"),
        allow_unicode=True,
        sort_keys=False,
    )

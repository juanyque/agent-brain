from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import ClassVar, Literal, override

from pydantic import BaseModel, ConfigDict, Field
from selection_inputs import SelectionProjectError


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class Reviewer(_FrozenModel):
    name: str = Field(min_length=1)
    professional_id: str = Field(min_length=1)
    signer_identity: str = Field(min_length=1)


class ExcludedClause(_FrozenModel):
    id: str
    reason_code: str = Field(min_length=1)


class ApprovalProvenance(_FrozenModel):
    catalog_sha256: str
    jurisdiction_sha256: str
    legal_source_snapshot_sha256: str


class LegalApproval(_FrozenModel):
    approval_version: Literal["0.1.0"]
    status: Literal["approved"]
    catalog: str
    jurisdiction: str
    reviewed_on: date
    reviewer: Reviewer
    approved_clause_versions: tuple[str, ...]
    excluded_clause_versions: tuple[ExcludedClause, ...]
    provenance: ApprovalProvenance


class LiveEvidence(_FrozenModel):
    source_id: str
    official_url: str
    resolved_url: str
    checked_at: datetime
    status_code: int
    content_sha256: str


class ResolvedCheck(_FrozenModel):
    id: str
    status: Literal["passed"]
    outcome_code: str = Field(min_length=1)
    evidence: tuple[LiveEvidence, ...]


class ResolutionProvenance(_FrozenModel):
    data_sha256: str
    jurisdiction_sha256: str
    sources_sha256: str


class JurisdictionResolution(_FrozenModel):
    resolution_version: Literal["0.1.0"]
    status: Literal["complete"]
    jurisdiction: str
    resolved_on: date
    valid_until: date
    checks: tuple[ResolvedCheck, ...]
    provenance: ResolutionProvenance


@dataclass(frozen=True, slots=True)
class PublicationEvidence:
    approval: LegalApproval
    resolution: JurisdictionResolution
    release_date: date
    approval_sha256: str
    jurisdiction_resolution_sha256: str


@dataclass(frozen=True, slots=True)
class GovernanceBindingError(SelectionProjectError):
    field: str
    expected: str
    actual: str

    @override
    def __str__(self) -> str:
        return (
            f"governance {self.field} does not match: "
            f"expected {self.expected}, got {self.actual}"
        )


@dataclass(frozen=True, slots=True)
class ClauseDecisionError(SelectionProjectError):
    decision: str
    clause_ids: tuple[str, ...]

    @override
    def __str__(self) -> str:
        return f"{self.decision}: {', '.join(self.clause_ids)}"


@dataclass(frozen=True, slots=True)
class CheckResolutionError(SelectionProjectError):
    reason: str
    check_ids: tuple[str, ...] = ()

    @override
    def __str__(self) -> str:
        suffix = f": {', '.join(self.check_ids)}" if self.check_ids else ""
        return f"jurisdiction checks {self.reason}{suffix}"


@dataclass(frozen=True, slots=True)
class ResolutionValidityError(SelectionProjectError):
    release_date: date
    resolved_on: date
    valid_until: date

    @override
    def __str__(self) -> str:
        return (
            f"jurisdiction resolution is not valid on {self.release_date}: "
            f"valid from {self.resolved_on} through {self.valid_until}"
        )

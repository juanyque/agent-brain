from __future__ import annotations

from clause_selection import BlockReason, ClauseSelection, GenerationReview, LegalReview
from governance_models import (
    CheckResolutionError,
    ClauseDecisionError,
    GovernanceBindingError,
    LegalApproval,
    PublicationEvidence,
    ResolutionValidityError,
)


def _require_binding(field: str, expected: str, actual: str) -> None:
    if expected != actual:
        raise GovernanceBindingError(
            field=field,
            expected=expected,
            actual=actual,
        )


def validate_approval(
    selection: ClauseSelection,
    approval: LegalApproval,
) -> tuple[str, ...]:
    """Validate exact clause decisions and their immutable review inputs."""
    _require_binding("catalog", selection.catalog, approval.catalog)
    _require_binding("jurisdiction", selection.jurisdiction, approval.jurisdiction)
    _require_binding(
        "catalog_sha256",
        selection.provenance.catalog_sha256,
        approval.provenance.catalog_sha256,
    )
    _require_binding(
        "approval jurisdiction_sha256",
        selection.provenance.jurisdiction_sha256,
        approval.provenance.jurisdiction_sha256,
    )
    _require_binding(
        "legal_source_snapshot_sha256",
        selection.provenance.legal_source_snapshot_sha256,
        approval.provenance.legal_source_snapshot_sha256,
    )
    if approval.approved_clause_versions != selection.candidate_clauses:
        missing = tuple(
            clause
            for clause in selection.candidate_clauses
            if clause not in approval.approved_clause_versions
        )
        unexpected = tuple(
            clause
            for clause in approval.approved_clause_versions
            if clause not in selection.candidate_clauses
        )
        raise ClauseDecisionError(
            decision="unapproved candidate clauses" if missing else "unexpected approvals",
            clause_ids=missing or unexpected,
        )
    missing_data = tuple(
        blocked.id
        for blocked in selection.blocked_clauses
        if BlockReason.MISSING_DATA in blocked.reasons
    )
    if missing_data:
        raise ClauseDecisionError(
            decision="clauses still blocked by missing data",
            clause_ids=missing_data,
        )
    expected_exclusions = tuple(blocked.id for blocked in selection.blocked_clauses)
    exclusions = tuple(item.id for item in approval.excluded_clause_versions)
    if exclusions != expected_exclusions:
        raise ClauseDecisionError(
            decision="legal-review exclusions do not match blocked clauses",
            clause_ids=expected_exclusions,
        )
    return exclusions


def apply_governance(
    selection: ClauseSelection,
    evidence: PublicationEvidence,
) -> ClauseSelection:
    """Bind exact legal and live-check evidence to a publishable selection."""
    approval = evidence.approval
    resolution = evidence.resolution
    release_date = evidence.release_date
    exclusions = validate_approval(selection, approval)
    _require_binding("resolution jurisdiction", selection.jurisdiction, resolution.jurisdiction)
    _require_binding(
        "data_sha256",
        selection.provenance.data_sha256,
        resolution.provenance.data_sha256,
    )
    _require_binding(
        "resolution jurisdiction_sha256",
        selection.provenance.jurisdiction_sha256,
        resolution.provenance.jurisdiction_sha256,
    )
    _require_binding(
        "sources_sha256",
        selection.provenance.sources_sha256,
        resolution.provenance.sources_sha256,
    )

    if approval.reviewed_on > release_date:
        raise ClauseDecisionError(
            decision="approval review date is after release date",
            clause_ids=approval.approved_clause_versions,
        )
    resolved_checks = tuple(check.id for check in resolution.checks)
    if resolved_checks != selection.generation_checks:
        raise CheckResolutionError(
            reason="do not match required order",
            check_ids=selection.generation_checks,
        )
    if not resolution.resolved_on <= release_date <= resolution.valid_until:
        raise ResolutionValidityError(
            release_date=release_date,
            resolved_on=resolution.resolved_on,
            valid_until=resolution.valid_until,
        )

    return selection.model_copy(
        update={
            "status": "reviewed-for-signature",
            "blocked_clauses": (),
            "legal_review": LegalReview(
                status="approved",
                approved_clause_versions=approval.approved_clause_versions,
                excluded_clause_versions=exclusions,
            ),
            "generation_review": GenerationReview(
                status="passed",
                resolved_checks=resolved_checks,
                valid_until=resolution.valid_until,
            ),
            "provenance": selection.provenance.model_copy(
                update={
                    "approval_sha256": evidence.approval_sha256,
                    "jurisdiction_resolution_sha256": (
                        evidence.jurisdiction_resolution_sha256
                    ),
                },
            ),
        },
    )

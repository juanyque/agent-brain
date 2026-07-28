from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from approval_ledger import ApprovalLedger, require_active_approval
from artifact_authenticity import SignatureVerification, verify_signature
from clause_selection import ClauseSelection
from document_governance import apply_governance
from governance_models import JurisdictionResolution, LegalApproval, PublicationEvidence
from selection_inputs import digest, load_yaml
from selection_project import PreparedSelection


@dataclass(frozen=True, slots=True)
class PublicationSpec:
    approval: Path
    approval_signature: Path
    approval_ledger: Path
    approval_ledger_signature: Path
    allowed_signers: Path
    jurisdiction_checks: Path
    release_date: date


def governed_selection(
    prepared: PreparedSelection,
    publication: PublicationSpec,
) -> ClauseSelection:
    approval = load_yaml(publication.approval, LegalApproval)
    ledger = load_yaml(publication.approval_ledger, ApprovalLedger)
    verify_signature(
        SignatureVerification(
            artifact=publication.approval,
            signature=publication.approval_signature,
            allowed_signers=publication.allowed_signers,
            signer_identity=approval.reviewer.signer_identity,
        ),
    )
    verify_signature(
        SignatureVerification(
            artifact=publication.approval_ledger,
            signature=publication.approval_ledger_signature,
            allowed_signers=publication.allowed_signers,
            signer_identity=ledger.signer_identity,
        ),
    )
    approval_sha256 = digest(publication.approval)
    require_active_approval(ledger, approval_sha256, publication.release_date)
    resolution = load_yaml(
        publication.jurisdiction_checks,
        JurisdictionResolution,
    )
    return apply_governance(
        prepared.selection,
        PublicationEvidence(
            approval=approval,
            resolution=resolution,
            release_date=publication.release_date,
            approval_sha256=approval_sha256,
            jurisdiction_resolution_sha256=digest(
                publication.jurisdiction_checks,
            ),
        ),
    )

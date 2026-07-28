from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import ClassVar, Literal, assert_never, override

from approval_ledger import (
    ApprovalLedger,
    ApprovalLedgerEntry,
    ApprovalStatus,
)
from governance_models import LegalApproval
from pydantic import BaseModel, ConfigDict
from selection_inputs import SelectionProjectError, digest, load_yaml, resolve


class ApprovalStatusUpdateFile(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    status_update_version: Literal["0.1.0"]
    project_type: str
    approval: Path
    action: ApprovalStatus
    effective_on: date
    valid_until: date
    signer_identity: str
    previous_ledger: Path | None = None
    replacement_approval: Path | None = None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class ApprovalTransitionError(SelectionProjectError):
    reason: str

    @override
    def __str__(self) -> str:
        return f"invalid approval status transition: {self.reason}"


def _require_active_previous(
    request: ApprovalStatusUpdateFile,
    previous: ApprovalLedger | None,
    approval_sha256: str,
) -> ApprovalLedger:
    if previous is None:
        raise ApprovalTransitionError(
            reason=f"{request.action} requires a previous ledger",
        )
    current = next(
        (
            entry
            for entry in previous.entries
            if entry.approval_sha256 == approval_sha256
        ),
        None,
    )
    match current:
        case ApprovalLedgerEntry(status=ApprovalStatus.ACTIVE):
            pass
        case None | ApprovalLedgerEntry():
            raise ApprovalTransitionError(
                reason="only an active approval can change status",
            )
        case unreachable:
            assert_never(unreachable)
    if previous.signer_identity != request.signer_identity:
        raise ApprovalTransitionError(
            reason="ledger signer identity cannot change between revisions",
        )
    return previous


def build_updated_ledger(request_path: Path) -> ApprovalLedger:
    """Build one auditable approval-status revision from a typed request."""
    request = load_yaml(request_path, ApprovalStatusUpdateFile)
    base = request_path.parent
    approval_path = resolve(request.approval, base)
    _ = load_yaml(approval_path, LegalApproval)
    approval_sha256 = digest(approval_path)
    previous_path = (
        resolve(request.previous_ledger, base)
        if request.previous_ledger is not None
        else None
    )
    previous = (
        load_yaml(previous_path, ApprovalLedger)
        if previous_path is not None
        else None
    )
    replacement_path = (
        resolve(request.replacement_approval, base)
        if request.replacement_approval is not None
        else None
    )

    match request.action:
        case ApprovalStatus.ACTIVE:
            match previous, replacement_path:
                case None, None:
                    pass
                case ApprovalLedger(), _:
                    raise ApprovalTransitionError(
                        reason=(
                            "activation starts a new ledger and cannot name "
                            "a previous ledger"
                        ),
                    )
                case None, Path():
                    raise ApprovalTransitionError(
                        reason="activation cannot name a replacement approval",
                    )
                case unreachable:
                    assert_never(unreachable)
            entries = (
                ApprovalLedgerEntry(
                    approval_sha256=approval_sha256,
                    status=ApprovalStatus.ACTIVE,
                    effective_on=request.effective_on,
                ),
            )
            revision = 1
        case ApprovalStatus.WITHDRAWN:
            active_previous = _require_active_previous(
                request,
                previous,
                approval_sha256,
            )
            match replacement_path:
                case None:
                    pass
                case Path():
                    raise ApprovalTransitionError(
                        reason="withdrawn cannot name a replacement approval",
                    )
                case unreachable:
                    assert_never(unreachable)
            changed = ApprovalLedgerEntry(
                approval_sha256=approval_sha256,
                status=ApprovalStatus.WITHDRAWN,
                effective_on=request.effective_on,
                reason_code=request.reason_code,
            )
            entries = tuple(
                changed if entry.approval_sha256 == approval_sha256 else entry
                for entry in active_previous.entries
            )
            revision = active_previous.revision + 1
        case ApprovalStatus.SUPERSEDED:
            active_previous = _require_active_previous(
                request,
                previous,
                approval_sha256,
            )
            match replacement_path:
                case Path():
                    _ = load_yaml(replacement_path, LegalApproval)
                    replacement_sha256 = digest(replacement_path)
                case None:
                    raise ApprovalTransitionError(
                        reason="superseded requires a replacement approval",
                    )
                case unreachable:
                    assert_never(unreachable)
            changed = ApprovalLedgerEntry(
                approval_sha256=approval_sha256,
                status=ApprovalStatus.SUPERSEDED,
                effective_on=request.effective_on,
                replacement_approval_sha256=replacement_sha256,
                reason_code=request.reason_code,
            )
            entries = tuple(
                changed if entry.approval_sha256 == approval_sha256 else entry
                for entry in active_previous.entries
            )
            entries = (
                *entries,
                ApprovalLedgerEntry(
                    approval_sha256=replacement_sha256,
                    status=ApprovalStatus.ACTIVE,
                    effective_on=request.effective_on,
                ),
            )
            revision = active_previous.revision + 1
        case unreachable:
            assert_never(unreachable)

    return ApprovalLedger(
        ledger_version="0.1.0",
        project_type=request.project_type,
        revision=revision,
        issued_on=request.effective_on,
        valid_until=request.valid_until,
        signer_identity=request.signer_identity,
        previous_ledger_sha256=(
            digest(previous_path) if previous_path is not None else None
        ),
        entries=entries,
    )

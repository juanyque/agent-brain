from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum, unique
from typing import ClassVar, Literal, assert_never, override

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError
from selection_inputs import SelectionProjectError


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


@unique
class ApprovalStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"
    SUPERSEDED = "superseded"


class ApprovalLedgerEntry(_FrozenModel):
    approval_sha256: str = Field(min_length=64, max_length=64)
    status: ApprovalStatus
    effective_on: date
    replacement_approval_sha256: str | None = None
    reason_code: str | None = None

    @model_validator(mode="after")
    def validate_transition_fields(self) -> ApprovalLedgerEntry:
        match self.status:
            case ApprovalStatus.ACTIVE:
                if self.replacement_approval_sha256 is not None:
                    raise PydanticCustomError(
                        "approval_status",
                        "active approval cannot name a replacement",
                    )
            case ApprovalStatus.WITHDRAWN:
                if self.reason_code is None:
                    raise PydanticCustomError(
                        "approval_status",
                        "withdrawn approval requires a reason code",
                    )
            case ApprovalStatus.SUPERSEDED:
                if self.replacement_approval_sha256 is None:
                    raise PydanticCustomError(
                        "approval_status",
                        "superseded approval requires a replacement",
                    )
            case unreachable:
                assert_never(unreachable)
        return self


class ApprovalLedger(_FrozenModel):
    ledger_version: Literal["0.1.0"]
    project_type: str = Field(min_length=1)
    revision: int = Field(gt=0)
    issued_on: date
    valid_until: date
    signer_identity: str = Field(min_length=1)
    previous_ledger_sha256: str | None = None
    entries: tuple[ApprovalLedgerEntry, ...] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class ApprovalStatusError(SelectionProjectError):
    approval_sha256: str
    reason: str
    replacement_approval_sha256: str | None = None

    @override
    def __str__(self) -> str:
        replacement = (
            f"; replacement {self.replacement_approval_sha256}"
            if self.replacement_approval_sha256 is not None
            else ""
        )
        return f"approval {self.approval_sha256} {self.reason}{replacement}"


def require_active_approval(
    ledger: ApprovalLedger,
    approval_sha256: str,
    release_date: date,
) -> None:
    """Require the approval to be active in a current signed ledger."""
    if not ledger.issued_on <= release_date <= ledger.valid_until:
        raise ApprovalStatusError(
            approval_sha256=approval_sha256,
            reason=(
                f"ledger is not valid on {release_date}; valid from "
                f"{ledger.issued_on} through {ledger.valid_until}"
            ),
        )
    entry = next(
        (
            candidate
            for candidate in ledger.entries
            if candidate.approval_sha256 == approval_sha256
        ),
        None,
    )
    if entry is None:
        raise ApprovalStatusError(
            approval_sha256=approval_sha256,
            reason="is absent from the approval ledger",
        )
    if entry.effective_on > release_date:
        raise ApprovalStatusError(
            approval_sha256=approval_sha256,
            reason=f"status is not effective until {entry.effective_on}",
        )
    match entry.status:
        case ApprovalStatus.ACTIVE:
            return
        case ApprovalStatus.WITHDRAWN:
            raise ApprovalStatusError(
                approval_sha256=approval_sha256,
                reason=f"is withdrawn ({entry.reason_code})",
            )
        case ApprovalStatus.SUPERSEDED:
            raise ApprovalStatusError(
                approval_sha256=approval_sha256,
                reason="is superseded",
                replacement_approval_sha256=entry.replacement_approval_sha256,
            )
        case unreachable:
            assert_never(unreachable)


def ledger_yaml(ledger: ApprovalLedger) -> str:
    return yaml.safe_dump(
        ledger.model_dump(mode="json"),
        allow_unicode=True,
        sort_keys=False,
    )

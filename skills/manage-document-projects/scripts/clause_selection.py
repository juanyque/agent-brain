from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum, unique
from typing import Annotated, ClassVar, Literal, TypeAlias, assert_never

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class DocumentData(RootModel[dict[str, JsonValue]]):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


class SourceReference(_FrozenModel):
    source_id: str
    provisions: tuple[str, ...]


class AlwaysApplicability(_FrozenModel):
    mode: Literal["always"]


class WhenApplicability(_FrozenModel):
    mode: Literal["when"]
    path: str
    equals: str | int | float | bool | None


ClauseApplicability = Annotated[
    AlwaysApplicability | WhenApplicability,
    Field(discriminator="mode"),
]


@unique
class Implementation(StrEnum):
    FRAGMENT_READY = "fragment-ready"
    SELECTOR_READY = "selector-ready"
    BLOCKED_LEGAL_REVIEW = "blocked-legal-review"


class Clause(_FrozenModel):
    id: str
    version: str
    title: str
    documents: tuple[str, ...]
    status: str
    implementation: Implementation
    fragment: str | None = None
    applicability: ClauseApplicability
    required_data: tuple[str, ...]
    source_refs: tuple[SourceReference, ...]

    @property
    def versioned_id(self) -> str:
        return f"{self.id}@{self.version}"


class ClauseCatalog(_FrozenModel):
    catalog_version: str
    id: str
    project_type: str
    version: str
    status: str
    legal_review: str
    default_jurisdiction: str
    clauses: tuple[Clause, ...]

    @property
    def versioned_id(self) -> str:
        return f"{self.id}@{self.version}"


class Provenance(_FrozenModel):
    data_sha256: str
    schema_sha256: str
    catalog_sha256: str
    jurisdiction_sha256: str
    sources_sha256: str
    legal_source_snapshot_sha256: str
    approval_sha256: str | None = None
    jurisdiction_resolution_sha256: str | None = None


@unique
class BlockReason(StrEnum):
    MISSING_DATA = "missing-data"
    LEGAL_REVIEW_REQUIRED = "legal-review-required"


class BlockedClause(_FrozenModel):
    id: str
    reasons: tuple[BlockReason, ...]
    missing_data_paths: tuple[str, ...] = ()


class LegalReview(_FrozenModel):
    status: Literal["required", "approved"] = "required"
    approved_clause_versions: tuple[str, ...] = ()
    excluded_clause_versions: tuple[str, ...] = ()


class GenerationReview(_FrozenModel):
    status: Literal["required", "passed"] = "required"
    resolved_checks: tuple[str, ...] = ()
    valid_until: date | None = None


class ClauseSelection(_FrozenModel):
    selection_version: Literal["0.3.0"] = "0.3.0"
    catalog: str
    jurisdiction: str
    data_revision: str
    document: str
    status: Literal[
        "draft-not-for-signature",
        "reviewed-for-signature",
    ] = "draft-not-for-signature"
    candidate_clauses: tuple[str, ...]
    blocked_clauses: tuple[BlockedClause, ...]
    not_applicable_clauses: tuple[str, ...]
    generation_checks: tuple[str, ...]
    legal_review: LegalReview = LegalReview()
    generation_review: GenerationReview = GenerationReview()
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class SelectionInputs:
    data: DocumentData
    catalog: ClauseCatalog
    document: str
    jurisdiction: str
    data_revision: str
    generation_checks: tuple[str, ...]
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class _ResolvedValue:
    value: JsonValue


@dataclass(frozen=True, slots=True)
class _MissingPath:
    path: str


_LookupResult: TypeAlias = _ResolvedValue | _MissingPath


@dataclass(frozen=True, slots=True)
class _Applicable:
    pass


@dataclass(frozen=True, slots=True)
class _NotApplicable:
    pass


_ApplicabilityResult: TypeAlias = _Applicable | _NotApplicable | _MissingPath


def _lookup(data: DocumentData, path: str) -> _LookupResult:
    current: JsonValue = data.root
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return _MissingPath(path=path)
        current = current[segment]
    return _ResolvedValue(value=current)


def _applicability(
    data: DocumentData,
    applicability: ClauseApplicability,
) -> _ApplicabilityResult:
    match applicability:
        case AlwaysApplicability():
            return _Applicable()
        case WhenApplicability(path=path, equals=expected):
            match _lookup(data, path):
                case _MissingPath():
                    return _MissingPath(path=path)
                case _ResolvedValue(value=value):
                    if value == expected:
                        return _Applicable()
                    return _NotApplicable()
                case unreachable:
                    assert_never(unreachable)
        case unreachable:
            assert_never(unreachable)


def _missing_paths(data: DocumentData, paths: tuple[str, ...]) -> tuple[str, ...]:
    missing: list[str] = []
    for path in paths:
        match _lookup(data, path):
            case _MissingPath():
                missing.append(path)
            case _ResolvedValue():
                pass
            case unreachable:
                assert_never(unreachable)
    return tuple(missing)


def select_clauses(inputs: SelectionInputs) -> ClauseSelection:
    """Select candidates and explain every blocked or non-applicable clause."""
    candidates: list[str] = []
    blocked: list[BlockedClause] = []
    not_applicable: list[str] = []

    for clause in inputs.catalog.clauses:
        if inputs.document not in clause.documents:
            continue

        match _applicability(inputs.data, clause.applicability):
            case _NotApplicable():
                not_applicable.append(clause.versioned_id)
                continue
            case _MissingPath(path=path):
                blocked.append(
                    BlockedClause(
                        id=clause.versioned_id,
                        reasons=(BlockReason.MISSING_DATA,),
                        missing_data_paths=(path,),
                    ),
                )
                continue
            case _Applicable():
                pass
            case unreachable:
                assert_never(unreachable)

        missing_paths = _missing_paths(inputs.data, clause.required_data)
        reasons: list[BlockReason] = []
        if missing_paths:
            reasons.append(BlockReason.MISSING_DATA)

        match clause.implementation:
            case Implementation.BLOCKED_LEGAL_REVIEW:
                reasons.append(BlockReason.LEGAL_REVIEW_REQUIRED)
            case Implementation.FRAGMENT_READY | Implementation.SELECTOR_READY:
                pass
            case unreachable:
                assert_never(unreachable)

        if reasons:
            blocked.append(
                BlockedClause(
                    id=clause.versioned_id,
                    reasons=tuple(reasons),
                    missing_data_paths=missing_paths,
                ),
            )
        else:
            candidates.append(clause.versioned_id)

    return ClauseSelection(
        catalog=inputs.catalog.versioned_id,
        jurisdiction=inputs.jurisdiction,
        data_revision=inputs.data_revision,
        document=inputs.document,
        candidate_clauses=tuple(candidates),
        blocked_clauses=tuple(blocked),
        not_applicable_clauses=tuple(not_applicable),
        generation_checks=inputs.generation_checks,
        provenance=inputs.provenance,
    )

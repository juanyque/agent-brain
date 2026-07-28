from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import ClassVar, Literal, override

import httpx2
import yaml
from governance_models import (
    JurisdictionResolution,
    LiveEvidence,
    ResolutionProvenance,
    ResolvedCheck,
)
from pydantic import BaseModel, ConfigDict, Field
from selection_inputs import (
    JurisdictionLayer,
    ProjectEnvelope,
    ProjectTypeManifest,
    SelectionProjectError,
    digest,
    load_yaml,
    resolve,
)
from selection_project import SelectionBuildRequest, build_selection


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class CheckResolutionRequest(_FrozenModel):
    id: str
    outcome_code: str = Field(min_length=1)
    source_ids: tuple[str, ...]


class ResolutionRequestFile(_FrozenModel):
    request_version: Literal["0.1.0"]
    project_type: Path
    data: Path
    document: str = "lease"
    resolved_on: date
    valid_until: date
    checks: tuple[CheckResolutionRequest, ...]


class RegisteredSource(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    id: str
    official_url: str
    preservation: str


class SourceRegistry(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    sources: tuple[RegisteredSource, ...]


@dataclass(frozen=True, slots=True)
class CheckSetError(SelectionProjectError):
    expected: tuple[str, ...]
    actual: tuple[str, ...]

    @override
    def __str__(self) -> str:
        return (
            "jurisdiction resolution checks do not match: "
            f"expected {', '.join(self.expected)}, got {', '.join(self.actual)}"
        )


@dataclass(frozen=True, slots=True)
class SourceSetError(SelectionProjectError):
    check_id: str
    expected: tuple[str, ...]
    actual: tuple[str, ...]

    @override
    def __str__(self) -> str:
        return (
            f"live sources for {self.check_id} do not match: "
            f"expected {', '.join(self.expected)}, got {', '.join(self.actual)}"
        )


@dataclass(frozen=True, slots=True)
class LiveSourceError(SelectionProjectError):
    source_id: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"cannot resolve live source {self.source_id}: {self.reason}"


@dataclass(frozen=True, slots=True)
class ResolutionDateError(SelectionProjectError):
    resolved_on: date
    valid_until: date

    @override
    def __str__(self) -> str:
        return (
            f"jurisdiction resolution expires before it starts: "
            f"{self.resolved_on} > {self.valid_until}"
        )


def _live_source_ids(
    refs: tuple[str, ...],
    sources: dict[str, RegisteredSource],
) -> tuple[str, ...]:
    return tuple(
        source_id
        for source_id in refs
        if source_id in sources
        and sources[source_id].preservation == "resolve-live"
    )


def _capture_evidence(
    source: RegisteredSource,
    client: httpx2.Client,
) -> LiveEvidence:
    try:
        response = client.get(source.official_url)
    except httpx2.HTTPError as error:
        raise LiveSourceError(source_id=source.id, reason=str(error)) from None
    return LiveEvidence(
        source_id=source.id,
        official_url=source.official_url,
        resolved_url=str(response.url),
        checked_at=datetime.now(UTC),
        status_code=response.status_code,
        content_sha256=sha256(response.content).hexdigest(),
    )


def resolve_checks(
    request_path: Path,
    client: httpx2.Client,
) -> JurisdictionResolution:
    """Capture official live evidence for every declared generation check."""
    request_file = load_yaml(request_path, ResolutionRequestFile)
    if request_file.valid_until < request_file.resolved_on:
        raise ResolutionDateError(
            resolved_on=request_file.resolved_on,
            valid_until=request_file.valid_until,
        )
    manifest_path = resolve(request_file.project_type, request_path.parent)
    data_path = resolve(request_file.data, request_path.parent)
    prepared = build_selection(
        SelectionBuildRequest(
            manifest=manifest_path,
            data=data_path,
            document=request_file.document,
        ),
    )
    manifest = load_yaml(manifest_path, ProjectTypeManifest)
    project = load_yaml(data_path, ProjectEnvelope).project
    reference = manifest.jurisdictions[project.jurisdiction]
    jurisdiction_path = resolve(reference.layer, manifest_path.parent)
    sources_path = resolve(reference.sources, manifest_path.parent)
    jurisdiction = load_yaml(jurisdiction_path, JurisdictionLayer)
    registry = load_yaml(sources_path, SourceRegistry)
    sources = {source.id: source for source in registry.sources}

    expected_checks = tuple(check.id for check in jurisdiction.generation_checks)
    actual_checks = tuple(check.id for check in request_file.checks)
    if actual_checks != expected_checks:
        raise CheckSetError(expected=expected_checks, actual=actual_checks)

    resolved: list[ResolvedCheck] = []
    for check_request, check_definition in zip(
        request_file.checks,
        jurisdiction.generation_checks,
        strict=True,
    ):
        expected_sources = _live_source_ids(
            check_definition.source_refs,
            sources,
        )
        if check_request.source_ids != expected_sources:
            raise SourceSetError(
                check_id=check_request.id,
                expected=expected_sources,
                actual=check_request.source_ids,
            )
        resolved.append(
            ResolvedCheck(
                id=check_request.id,
                status="passed",
                outcome_code=check_request.outcome_code,
                evidence=tuple(
                    _capture_evidence(sources[source_id], client)
                    for source_id in check_request.source_ids
                ),
            ),
        )

    return JurisdictionResolution(
        resolution_version="0.1.0",
        status="complete",
        jurisdiction=jurisdiction.versioned_id,
        resolved_on=request_file.resolved_on,
        valid_until=request_file.valid_until,
        checks=tuple(resolved),
        provenance=ResolutionProvenance(
            data_sha256=prepared.selection.provenance.data_sha256,
            jurisdiction_sha256=digest(jurisdiction_path),
            sources_sha256=digest(sources_path),
        ),
    )


def resolution_yaml(resolution: JurisdictionResolution) -> str:
    """Serialize resolved checks as a stable YAML artifact."""
    return yaml.safe_dump(
        resolution.model_dump(mode="json"),
        allow_unicode=True,
        sort_keys=False,
    )

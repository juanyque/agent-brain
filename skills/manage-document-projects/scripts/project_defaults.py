from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, override

from clause_selection import DocumentData
from document_preflight import (
    DocumentPreflightRequest,
    require_document_data,
    required_paths,
)
from project_derivations import (
    DefaultRules,
    InvalidNumericFieldError,
    derive_project_data,
)
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from selection_inputs import (
    ProjectEnvelope,
    ProjectTypeManifest,
    SelectionProjectError,
    digest,
    load_yaml,
    resolve,
)

_OVERRIDE_NAME = "defaults.override.yaml"

__all__ = [
    "DefaultRules",
    "DefaultsOverride",
    "DefaultsPackage",
    "DefaultsResolution",
    "InvalidNumericFieldError",
    "PublicationReadinessError",
    "ResolvedProjectData",
    "UnknownDefaultsProfileError",
    "derive_project_data",
    "require_publication_ready",
    "reservation_publication_blockers",
    "resolve_project_data",
]


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class DefaultsPackage(_FrozenModel):
    defaults_version: Literal["0.1.0"]
    profile: str
    data: dict[str, JsonValue]
    rules: DefaultRules


class DefaultsOverride(_FrozenModel):
    data: dict[str, JsonValue] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DefaultsResolution:
    profile: str
    profile_path: Path
    profile_sha256: str
    override_path: Path | None
    override_sha256: str | None


@dataclass(frozen=True, slots=True)
class ResolvedProjectData:
    data: DocumentData
    defaults: DefaultsResolution | None


@dataclass(frozen=True, slots=True)
class UnknownDefaultsProfileError(SelectionProjectError):
    profile: str

    @override
    def __str__(self) -> str:
        return f"project type does not declare defaults profile: {self.profile}"


@dataclass(frozen=True, slots=True)
class PublicationReadinessError(SelectionProjectError):
    document: str
    blockers: tuple[str, ...]

    @override
    def __str__(self) -> str:
        return f"{self.document} publication blocked: {', '.join(self.blockers)}"


def _merge(
    base: dict[str, JsonValue],
    overlay: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    merged = dict(base)
    for key, overlay_value in overlay.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(overlay_value, dict):
            merged[key] = (
                dict(overlay_value)
                if "enabled" in overlay_value
                and overlay_value.get("enabled") != base_value.get("enabled")
                else _merge(base_value, overlay_value)
            )
        else:
            merged[key] = overlay_value
    return merged


def resolve_project_data(
    manifest_path: Path,
    data_path: Path,
    document: str | None = None,
) -> ResolvedProjectData:
    manifest = load_yaml(manifest_path, ProjectTypeManifest)
    instance = load_yaml(data_path, DocumentData)
    project = ProjectEnvelope.model_validate(instance.root).project
    if project.defaults_profile is None:
        require_document_data(
            DocumentPreflightRequest(
                root=instance.root,
                document=document or "project",
                data_path=data_path,
                required_paths=required_paths(manifest, document),
            ),
        )
        return ResolvedProjectData(data=instance, defaults=None)
    try:
        profile_ref = manifest.defaults_profiles[project.defaults_profile]
    except KeyError:
        raise UnknownDefaultsProfileError(profile=project.defaults_profile) from None

    profile_path = resolve(profile_ref, manifest_path.parent)
    package = load_yaml(profile_path, DefaultsPackage)
    merged = _merge(package.data, instance.root)
    override_path = data_path.parent / _OVERRIDE_NAME
    override_sha256: str | None = None
    if override_path.is_file():
        override = load_yaml(override_path, DefaultsOverride)
        merged = _merge(package.data, override.data)
        merged = _merge(merged, instance.root)
        override_sha256 = digest(override_path)
    require_document_data(
        DocumentPreflightRequest(
            root=merged,
            document=document or "project",
            data_path=data_path,
            required_paths=required_paths(manifest, document),
        ),
    )
    return ResolvedProjectData(
        data=DocumentData.model_validate(derive_project_data(merged, package.rules)),
        defaults=DefaultsResolution(
            profile=package.profile,
            profile_path=profile_path,
            profile_sha256=digest(profile_path),
            override_path=override_path if override_path.is_file() else None,
            override_sha256=override_sha256,
        ),
    )


def reservation_publication_blockers(data: DocumentData) -> tuple[str, ...]:
    operation = data.root.get("operation")
    if not isinstance(operation, dict):
        return ("reservation-data-missing",)
    reservation = operation.get("reservation")
    if not isinstance(reservation, dict):
        return ("reservation-data-missing",)
    blockers: list[str] = []
    payment_terms = reservation.get("payment_terms")
    if not isinstance(payment_terms, dict) or payment_terms.get("mode") == "pending":
        blockers.append("reservation-payment-mode-unresolved")
    return tuple(blockers)


def require_publication_ready(data: DocumentData, document: str) -> None:
    blockers = (
        reservation_publication_blockers(data) if document == "reservation" else ()
    )
    if blockers:
        raise PublicationReadinessError(document=document, blockers=blockers)

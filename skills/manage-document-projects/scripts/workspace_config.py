from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Self, override

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from pydantic_core import PydanticCustomError
from selection_inputs import InputError, SelectionProjectError, digest, load_yaml

CONFIG_SCHEMA_VERSION = "manage-document-projects/config/v1"
DEFAULT_PROFILE = "default"
PROFILE_NAME = re.compile(r"^[a-z][a-z0-9-]*$")


class OptionalToolChoice(StrEnum):
    INSTALL = "install"
    DECLINE = "decline"


class GitVisibility(StrEnum):
    REQUIRED = "required"
    UNRESTRICTED = "unrestricted"


class IngestPolicy(StrEnum):
    FORBIDDEN = "forbidden"


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class OptionalTools(_FrozenModel):
    weasyprint: OptionalToolChoice
    libreoffice: OptionalToolChoice
    openssh: OptionalToolChoice


class WorkspaceLocations(_FrozenModel):
    projects: Path
    deliverables: Path
    incoming: Path

    @field_validator("projects", "deliverables", "incoming")
    @classmethod
    def require_relative_path(cls, value: Path) -> Path:
        if value.is_absolute() or ".." in value.parts:
            raise PydanticCustomError(
                "relative_workspace_path",
                "workspace location must be relative and cannot contain '..'",
            )
        return value


class WorkspacePolicies(_FrozenModel):
    deliverables_git_visibility: GitVisibility
    ingest_from_deliverables: IngestPolicy


class WorkspaceProfile(_FrozenModel):
    workspace_root: Path
    locations: WorkspaceLocations
    policies: WorkspacePolicies

    @field_validator("workspace_root")
    @classmethod
    def require_absolute_root(cls, value: Path) -> Path:
        expanded = value.expanduser()
        if not expanded.is_absolute():
            raise PydanticCustomError(
                "absolute_workspace_root",
                "workspace_root must be absolute",
            )
        return expanded.resolve(strict=False)


class WorkspaceConfig(_FrozenModel):
    schema_version: str
    default_profile: str
    optional_tools: OptionalTools
    profiles: dict[str, WorkspaceProfile]

    @field_validator("schema_version")
    @classmethod
    def require_schema_version(cls, value: str) -> str:
        if value != CONFIG_SCHEMA_VERSION:
            raise PydanticCustomError(
                "workspace_config_version",
                "unsupported configuration schema version",
            )
        return value

    @model_validator(mode="after")
    def require_default_profile(self) -> Self:
        invalid = tuple(
            profile
            for profile in self.profiles
            if PROFILE_NAME.fullmatch(profile) is None
        )
        if invalid or PROFILE_NAME.fullmatch(self.default_profile) is None:
            raise PydanticCustomError(
                "workspace_profile_name",
                "profile names must match ^[a-z][a-z0-9-]*$",
            )
        if self.default_profile not in self.profiles:
            raise PydanticCustomError(
                "default_workspace_profile",
                "default_profile must name an existing profile",
            )
        return self


@dataclass(frozen=True, slots=True)
class ResolvedWorkspace:
    profile: str
    config_path: Path
    config_sha256: str
    workspace_root: Path
    projects_root: Path
    deliverables_root: Path
    incoming_root: Path
    policies: WorkspacePolicies


@dataclass(frozen=True, slots=True)
class ProfileNotFoundError(SelectionProjectError):
    profile: str
    config_path: Path

    @override
    def __str__(self) -> str:
        return f"profile {self.profile!r} is not defined in {self.config_path}"


@dataclass(frozen=True, slots=True)
class WorkspacePathError(SelectionProjectError):
    profile: str
    path: Path
    workspace_root: Path

    @override
    def __str__(self) -> str:
        return (
            f"profile {self.profile!r} resolves outside its workspace root "
            f"{self.workspace_root}: {self.path}"
        )


def default_config_path() -> Path:
    override = os.environ.get("DOCUMENT_PROJECT_CONFIG_PATH")
    if override:
        return Path(override).expanduser().resolve(strict=False)
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return base / "manage-document-projects" / "config.yaml"


def load_config(path: Path | None = None) -> WorkspaceConfig:
    resolved = path or default_config_path()
    return load_yaml(resolved, WorkspaceConfig)


def configuration_yaml(configuration: WorkspaceConfig) -> str:
    return yaml.safe_dump(
        configuration.model_dump(mode="json"),
        allow_unicode=True,
        sort_keys=False,
    )


def resolve_workspace(
    configuration: WorkspaceConfig,
    config_path: Path,
    profile: str | None = None,
) -> ResolvedWorkspace:
    selected = profile or configuration.default_profile
    try:
        definition = configuration.profiles[selected]
    except KeyError:
        raise ProfileNotFoundError(
            profile=selected,
            config_path=config_path,
        ) from None
    root = definition.workspace_root.resolve(strict=False)
    projects = (root / definition.locations.projects).resolve(strict=False)
    deliverables = (root / definition.locations.deliverables).resolve(strict=False)
    incoming = (root / definition.locations.incoming).resolve(strict=False)
    for candidate in (projects, deliverables, incoming):
        try:
            _ = candidate.relative_to(root)
        except ValueError:
            raise WorkspacePathError(
                profile=selected,
                path=candidate,
                workspace_root=root,
            ) from None
    try:
        config_sha256 = digest(config_path)
    except OSError as error:
        raise InputError(path=config_path, reason=str(error)) from None
    return ResolvedWorkspace(
        profile=selected,
        config_path=config_path,
        config_sha256=config_sha256,
        workspace_root=root,
        projects_root=projects,
        deliverables_root=deliverables,
        incoming_root=incoming,
        policies=definition.policies,
    )


def load_workspace(profile: str | None = None) -> ResolvedWorkspace:
    path = default_config_path()
    return resolve_workspace(load_config(path), path, profile)

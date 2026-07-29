from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, override

import typer
from pydantic import BaseModel, ConfigDict
from selection_inputs import SelectionProjectError
from workspace_config import (
    GitVisibility,
    OptionalToolChoice,
    OptionalTools,
    WorkspaceLocations,
    WorkspacePolicies,
)


class SetupOverrides(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    profile: str | None
    workspace_root: Path | None
    projects: Path | None
    deliverables: Path | None
    incoming: Path | None
    git_visibility: GitVisibility | None
    weasyprint: OptionalToolChoice | None
    libreoffice: OptionalToolChoice | None
    openssh: OptionalToolChoice | None

    @classmethod
    def from_environment(cls) -> SetupOverrides:
        def value(name: str) -> str | None:
            candidate = os.environ.get(name)
            return candidate if candidate else None

        return cls.model_validate(
            {
                "profile": value("DOCUMENT_PROJECT_PROFILE"),
                "workspace_root": value("DOCUMENT_PROJECT_WORKSPACE_ROOT"),
                "projects": value("DOCUMENT_PROJECT_PROJECTS_DIR"),
                "deliverables": value("DOCUMENT_PROJECT_DELIVERABLES_DIR"),
                "incoming": value("DOCUMENT_PROJECT_INCOMING_DIR"),
                "git_visibility": value("DOCUMENT_PROJECT_GIT_VISIBILITY"),
                "weasyprint": value("DOCUMENT_PROJECT_WEASYPRINT_CHOICE"),
                "libreoffice": value("DOCUMENT_PROJECT_LIBREOFFICE_CHOICE"),
                "openssh": value("DOCUMENT_PROJECT_OPENSSH_CHOICE"),
            },
        )


@dataclass(frozen=True, slots=True)
class ConfigurationDefaults:
    profile: str
    workspace_root: Path | None
    locations: WorkspaceLocations
    policies: WorkspacePolicies
    optional_tools: OptionalTools


@dataclass(frozen=True, slots=True)
class ConfigurationValues:
    profile: str
    workspace_root: Path
    locations: WorkspaceLocations
    policies: WorkspacePolicies
    optional_tools: OptionalTools


@dataclass(frozen=True, slots=True)
class WorkspaceRootRequiredError(SelectionProjectError):
    @override
    def __str__(self) -> str:
        return (
            "non-interactive setup requires --workspace-root "
            "or DOCUMENT_PROJECT_WORKSPACE_ROOT"
        )


def _prompt_tool(label: str, current: OptionalToolChoice) -> OptionalToolChoice:
    install = typer.confirm(
        f"Install {label} when it is missing?",
        default=current is OptionalToolChoice.INSTALL,
    )
    return OptionalToolChoice.INSTALL if install else OptionalToolChoice.DECLINE


def collect_values(
    defaults: ConfigurationDefaults,
    overrides: SetupOverrides,
    interactive: bool,
) -> ConfigurationValues:
    if not interactive:
        if defaults.workspace_root is None:
            raise WorkspaceRootRequiredError
        return ConfigurationValues(
            profile=defaults.profile,
            workspace_root=defaults.workspace_root,
            locations=defaults.locations,
            policies=defaults.policies,
            optional_tools=defaults.optional_tools,
        )
    root = Path(
        typer.prompt(
            "Workspace root",
            default=(
                str(defaults.workspace_root)
                if defaults.workspace_root is not None
                else str(Path.cwd())
            ),
        ),
    ).expanduser()
    locations = WorkspaceLocations(
        projects=Path(
            typer.prompt(
                "Projects directory", default=str(defaults.locations.projects)
            ),
        ),
        deliverables=Path(
            typer.prompt(
                "Printable deliverables directory",
                default=str(defaults.locations.deliverables),
            ),
        ),
        incoming=Path(
            typer.prompt(
                "Incoming documents directory", default=str(defaults.locations.incoming)
            ),
        ),
    )
    tools = OptionalTools(
        weasyprint=(
            overrides.weasyprint
            or _prompt_tool("WeasyPrint", defaults.optional_tools.weasyprint)
        ),
        libreoffice=(
            overrides.libreoffice
            or _prompt_tool("LibreOffice", defaults.optional_tools.libreoffice)
        ),
        openssh=(
            overrides.openssh
            or _prompt_tool("OpenSSH", defaults.optional_tools.openssh)
        ),
    )
    return ConfigurationValues(
        profile=defaults.profile,
        workspace_root=root.resolve(strict=False),
        locations=locations,
        policies=defaults.policies,
        optional_tools=tools,
    )

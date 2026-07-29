from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from workspace_config import (
    DEFAULT_PROFILE,
    GitVisibility,
    IngestPolicy,
    OptionalToolChoice,
    OptionalTools,
    WorkspaceConfig,
    WorkspaceLocations,
    WorkspacePolicies,
    default_config_path,
    load_config,
)
from workspace_config_store import (
    WorkspaceUpdate,
    updated_configuration,
    write_configuration,
)
from workspace_setup_inputs import (
    ConfigurationDefaults,
    SetupOverrides,
    collect_values,
)


@dataclass(frozen=True, slots=True)
class ConfigurationOutcome:
    path: Path
    configuration: WorkspaceConfig
    changed: bool | None


def _defaults(
    configuration: WorkspaceConfig | None,
    overrides: SetupOverrides,
) -> ConfigurationDefaults:
    profile = overrides.profile or (
        configuration.default_profile if configuration is not None else DEFAULT_PROFILE
    )
    existing = (
        configuration.profiles.get(profile) if configuration is not None else None
    )
    return ConfigurationDefaults(
        profile=profile,
        workspace_root=(
            overrides.workspace_root
            or (existing.workspace_root if existing is not None else None)
        ),
        locations=WorkspaceLocations(
            projects=overrides.projects
            or (
                existing.locations.projects
                if existing is not None
                else Path("projects")
            ),
            deliverables=overrides.deliverables
            or (
                existing.locations.deliverables
                if existing is not None
                else Path("exports")
            ),
            incoming=overrides.incoming
            or (existing.locations.incoming if existing is not None else Path("inbox")),
        ),
        policies=WorkspacePolicies(
            deliverables_git_visibility=overrides.git_visibility
            or (
                existing.policies.deliverables_git_visibility
                if existing is not None
                else GitVisibility.UNRESTRICTED
            ),
            ingest_from_deliverables=IngestPolicy.FORBIDDEN,
        ),
        optional_tools=OptionalTools(
            weasyprint=overrides.weasyprint
            or (
                configuration.optional_tools.weasyprint
                if configuration is not None
                else OptionalToolChoice.DECLINE
            ),
            libreoffice=overrides.libreoffice
            or (
                configuration.optional_tools.libreoffice
                if configuration is not None
                else OptionalToolChoice.DECLINE
            ),
            openssh=overrides.openssh
            or (
                configuration.optional_tools.openssh
                if configuration is not None
                else OptionalToolChoice.DECLINE
            ),
        ),
    )


def configure_workspace(
    apply: bool,
    non_interactive: bool,
) -> ConfigurationOutcome:
    path = default_config_path()
    existing = load_config(path) if path.is_file() else None
    overrides = SetupOverrides.from_environment()
    interactive = not non_interactive and sys.stdin.isatty()
    values = collect_values(_defaults(existing, overrides), overrides, interactive)
    configuration = updated_configuration(
        existing,
        WorkspaceUpdate(
            profile=values.profile,
            workspace_root=values.workspace_root,
            locations=values.locations,
            policies=values.policies,
            optional_tools=values.optional_tools,
        ),
    )
    if not apply:
        return ConfigurationOutcome(
            path=path,
            configuration=configuration,
            changed=None,
        )
    for location in (
        values.locations.projects,
        values.locations.deliverables,
        values.locations.incoming,
    ):
        _ = (values.workspace_root / location).mkdir(parents=True, exist_ok=True)
    return ConfigurationOutcome(
        path=path,
        configuration=configuration,
        changed=write_configuration(path, configuration),
    )

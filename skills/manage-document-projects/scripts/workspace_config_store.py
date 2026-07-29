from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from workspace_config import (
    CONFIG_SCHEMA_VERSION,
    OptionalTools,
    WorkspaceConfig,
    WorkspaceLocations,
    WorkspacePolicies,
    WorkspaceProfile,
    configuration_yaml,
)


@dataclass(frozen=True, slots=True)
class WorkspaceUpdate:
    profile: str
    workspace_root: Path
    locations: WorkspaceLocations
    policies: WorkspacePolicies
    optional_tools: OptionalTools


def updated_configuration(
    existing: WorkspaceConfig | None,
    update: WorkspaceUpdate,
) -> WorkspaceConfig:
    profiles = dict(existing.profiles) if existing is not None else {}
    profiles[update.profile] = WorkspaceProfile(
        workspace_root=update.workspace_root,
        locations=update.locations,
        policies=update.policies,
    )
    return WorkspaceConfig(
        schema_version=CONFIG_SCHEMA_VERSION,
        default_profile=(
            existing.default_profile if existing is not None else update.profile
        ),
        optional_tools=update.optional_tools,
        profiles=profiles,
    )


def write_configuration(path: Path, configuration: WorkspaceConfig) -> bool:
    rendered = configuration_yaml(configuration)
    if path.is_file() and path.read_text(encoding="utf-8") == rendered:
        return False
    _ = path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as stream:
        _ = stream.write(rendered)
        temporary = Path(stream.name)
    try:
        _ = temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return True

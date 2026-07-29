from __future__ import annotations

import os
from pathlib import Path

import yaml


def workspace_environment(
    workspace: Path,
    deliverables: Path | None = None,
    git_visibility: str = "unrestricted",
) -> dict[str, str]:
    config = workspace / ".document-project-config.yaml"
    deliverables_location = deliverables or Path(".")
    _ = config.write_text(
        yaml.safe_dump(
            {
                "schema_version": "manage-document-projects/config/v1",
                "default_profile": "default",
                "optional_tools": {
                    "weasyprint": "decline",
                    "libreoffice": "decline",
                    "openssh": "decline",
                },
                "profiles": {
                    "default": {
                        "workspace_root": str(workspace.resolve()),
                        "locations": {
                            "projects": ".",
                            "deliverables": str(deliverables_location),
                            "incoming": "inbox",
                        },
                        "policies": {
                            "deliverables_git_visibility": git_visibility,
                            "ingest_from_deliverables": "forbidden",
                        },
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return {
        **os.environ,
        "DOCUMENT_PROJECT_CONFIG_PATH": str(config),
    }

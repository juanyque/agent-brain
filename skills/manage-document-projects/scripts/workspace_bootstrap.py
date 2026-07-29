from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import override

from selection_inputs import SelectionProjectError
from workspace_config import ResolvedWorkspace, default_config_path, load_workspace


@dataclass(frozen=True, slots=True)
class WorkspaceSetupError(SelectionProjectError):
    config_path: Path
    returncode: int

    @override
    def __str__(self) -> str:
        return (
            f"workspace setup failed with exit {self.returncode}; "
            f"configuration was not created at {self.config_path}"
        )


def ensure_workspace(profile: str | None = None) -> ResolvedWorkspace:
    config_path = default_config_path()
    if not config_path.is_file():
        setup = Path(__file__).resolve().with_name("setup.sh")
        command = ["bash", str(setup), "--apply"]
        if profile is not None:
            command.extend(("--profile", profile))
        if os.environ.get("DOCUMENT_PROJECT_SETUP_NON_INTERACTIVE") == "1":
            command.append("--non-interactive")
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            raise WorkspaceSetupError(
                config_path=config_path,
                returncode=result.returncode,
            )
    return load_workspace(profile)

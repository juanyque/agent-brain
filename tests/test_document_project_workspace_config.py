from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RENDERER = (
    ROOT / "skills" / "manage-document-projects" / "scripts" / "render_document.py"
)


def write_config(path: Path, default_root: Path, alternate_root: Path) -> None:
    _ = path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "manage-document-projects/config/v1",
                "default_profile": "default",
                "optional_tools": {
                    "weasyprint": "install",
                    "libreoffice": "decline",
                    "openssh": "install",
                },
                "profiles": {
                    "default": {
                        "workspace_root": str(default_root),
                        "locations": {
                            "projects": "projects",
                            "deliverables": "exports",
                            "incoming": "inbox",
                        },
                        "policies": {
                            "deliverables_git_visibility": "unrestricted",
                            "ingest_from_deliverables": "forbidden",
                        },
                    },
                    "alternate": {
                        "workspace_root": str(alternate_root),
                        "locations": {
                            "projects": "projects",
                            "deliverables": "exports",
                            "incoming": "inbox",
                        },
                        "policies": {
                            "deliverables_git_visibility": "unrestricted",
                            "ingest_from_deliverables": "forbidden",
                        },
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def run_renderer(
    workspace: Path,
    config: Path,
    output: Path,
    *options: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    template = workspace / "template.md.j2"
    data = workspace / "data.yaml"
    _ = template.write_text("# {{ title }}\n", encoding="utf-8")
    _ = data.write_text("title: Configured output\n", encoding="utf-8")
    return subprocess.run(
        [
            "uv",
            "run",
            "--script",
            str(RENDERER),
            str(template),
            str(data),
            str(output),
            *options,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "DOCUMENT_PROJECT_CONFIG_PATH": str(config),
            **(environment or {}),
        },
    )


def test_renderer_uses_default_profile_when_profile_is_omitted() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        config = workspace / "config.yaml"
        default_root = workspace / "default"
        alternate_root = workspace / "alternate"
        write_config(config, default_root, alternate_root)
        output = alternate_root / "exports" / "document.pdf"

        # When
        result = run_renderer(workspace, config, output)

        # Then
        assert result.returncode != 0
        assert "printable output must be inside" in result.stdout + result.stderr
        assert not output.exists()


def test_renderer_uses_an_explicit_profile() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        config = workspace / "config.yaml"
        default_root = workspace / "default"
        alternate_root = workspace / "alternate"
        write_config(config, default_root, alternate_root)
        output = alternate_root / "exports" / "document.pdf"

        # When
        result = run_renderer(
            workspace,
            config,
            output,
            "--profile",
            "alternate",
        )

        # Then
        assert result.returncode == 0, result.stdout + result.stderr
        assert output.read_bytes().startswith(b"%PDF-")


def test_renderer_bootstraps_a_missing_configuration() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        config = workspace / "config.yaml"
        output = workspace / "exports" / "document.pdf"

        # When
        result = run_renderer(
            workspace,
            config,
            output,
            environment={
                "DOCUMENT_PROJECT_SETUP_NON_INTERACTIVE": "1",
                "DOCUMENT_PROJECT_WORKSPACE_ROOT": str(workspace),
                "DOCUMENT_PROJECT_PROJECTS_DIR": "projects",
                "DOCUMENT_PROJECT_DELIVERABLES_DIR": "exports",
                "DOCUMENT_PROJECT_INCOMING_DIR": "inbox",
                "DOCUMENT_PROJECT_WEASYPRINT_CHOICE": "install",
                "DOCUMENT_PROJECT_LIBREOFFICE_CHOICE": "decline",
                "DOCUMENT_PROJECT_OPENSSH_CHOICE": "install",
            },
        )

        # Then
        assert result.returncode == 0, result.stdout + result.stderr
        assert config.is_file()
        configured = yaml.safe_load(config.read_text(encoding="utf-8"))
        assert configured["default_profile"] == "default"
        assert configured["optional_tools"]["libreoffice"] == "decline"
        assert output.read_bytes().startswith(b"%PDF-")

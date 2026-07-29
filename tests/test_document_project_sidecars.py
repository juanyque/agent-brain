from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from document_project_workspace import workspace_environment

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "manage-document-projects"
RENDERER = SKILL / "scripts" / "render_document.py"
PACKAGE = SKILL / "assets" / "project-types" / "residential-lease"
TEMPLATE = PACKAGE / "templates" / "reservation.md.j2"
DATA = PACKAGE / "examples" / "minimal-project.yaml"


def _render(output: Path, *options: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "--script",
            str(RENDERER),
            str(TEMPLATE),
            str(DATA),
            str(output),
            *options,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=workspace_environment(output.parent),
    )


def test_draft_render_omits_regenerable_sidecars_by_default() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        output = Path(raw) / "reservation.pdf"

        # When
        result = _render(output)

        # Then
        assert result.returncode == 0, result.stdout + result.stderr
        assert output.is_file()
        assert output.with_suffix(".md").is_file()
        assert not output.with_suffix(".selection.yaml").exists()
        assert not output.with_suffix(".provenance.yaml").exists()


def test_keep_sidecars_preserves_selection_and_provenance() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        output = Path(raw) / "reservation.pdf"

        # When
        result = _render(output, "--keep-sidecars")

        # Then
        assert result.returncode == 0, result.stdout + result.stderr
        assert output.with_suffix(".selection.yaml").is_file()
        assert output.with_suffix(".provenance.yaml").is_file()


def test_replace_without_keep_sidecars_removes_stale_sidecars() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        output = Path(raw) / "reservation.pdf"
        initial = _render(output, "--keep-sidecars")
        assert initial.returncode == 0, initial.stdout + initial.stderr

        # When
        result = _render(output, "--replace")

        # Then
        assert result.returncode == 0, result.stdout + result.stderr
        assert not output.with_suffix(".selection.yaml").exists()
        assert not output.with_suffix(".provenance.yaml").exists()

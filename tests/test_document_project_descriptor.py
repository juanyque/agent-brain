from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "manage-document-projects"
SCHEMA = SKILL_DIR / "assets" / "schemas" / "project-descriptor.schema.json"
EXAMPLE = SKILL_DIR / "assets" / "examples" / "minimal-project-descriptor.yaml"


def test_synthetic_project_descriptor_matches_schema() -> None:
    # Given
    command = [
        "uvx",
        "check-jsonschema",
        "--schemafile",
        str(SCHEMA),
        str(EXAMPLE),
    ]

    # When
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    # Then
    assert result.returncode == 0, result.stdout + result.stderr


def test_project_descriptor_rejects_personal_fields(tmp_path: Path) -> None:
    # Given
    invalid_descriptor = tmp_path / "invalid-project.yaml"
    _ = invalid_descriptor.write_text(
        EXAMPLE.read_text(encoding="utf-8").replace(
            "  status: planning\n",
            "  status: planning\n  landlord_name: Person Example\n",
            1,
        ),
        encoding="utf-8",
    )

    # When
    result = subprocess.run(
        [
            "uvx",
            "check-jsonschema",
            "--schemafile",
            str(SCHEMA),
            str(invalid_descriptor),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    # Then
    assert result.returncode != 0


def test_blocked_gate_requires_a_pending_check(tmp_path: Path) -> None:
    # Given
    inconsistent_descriptor = tmp_path / "inconsistent-project.yaml"
    _ = inconsistent_descriptor.write_text(
        EXAMPLE.read_text(encoding="utf-8").replace("pending", "passed"),
        encoding="utf-8",
    )

    # When
    result = subprocess.run(
        [
            "uvx",
            "check-jsonschema",
            "--schemafile",
            str(SCHEMA),
            str(inconsistent_descriptor),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    # Then
    assert result.returncode != 0

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

import yaml
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "manage-document-projects"
RENDERER = SKILL / "scripts" / "render_document.py"
PACKAGE = SKILL / "assets" / "project-types" / "residential-lease"
TEMPLATE = PACKAGE / "templates" / "lease.md.j2"
COMPLETE_DATA = PACKAGE / "examples" / "minimal-project.yaml"


class _BlockedClause(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    reasons: tuple[str, ...]
    missing_data_paths: tuple[str, ...] = ()


class _Selection(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    candidate_clauses: tuple[str, ...]
    blocked_clauses: tuple[_BlockedClause, ...]
    not_applicable_clauses: tuple[str, ...]


class SelectedDocumentRendererTests(unittest.TestCase):
    def test_lease_renderer_assembles_selected_clause_fragments(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            output = workspace / "lease.pdf"

            # When
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "--script",
                    str(RENDERER),
                    str(TEMPLATE),
                    str(COMPLETE_DATA),
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Then
            assert result.returncode == 0, result.stdout + result.stderr
            rendered = output.with_suffix(".md").read_text(encoding="utf-8")
            selection = _Selection.model_validate(
                yaml.safe_load(
                    output.with_suffix(".selection.yaml").read_text(
                        encoding="utf-8",
                    ),
                ),
            )
            assert len(selection.candidate_clauses) == 9
            assert selection.blocked_clauses == (
                _BlockedClause(
                    id="lease.notices-and-disputes@0.1.0",
                    reasons=("legal-review-required",),
                ),
            )
            for clause_id in (
                "lease.rent-update@0.1.0",
                "lease.conservation-and-works@0.1.0",
                "lease.expenses-and-supplies@0.1.0",
                "lease.assignment-subletting-and-preemption@0.1.0",
                "lease.withdrawal-and-termination@0.1.0",
            ):
                with self.subTest(clause_id=clause_id):
                    assert f"<!-- clause: {clause_id} -->" in rendered
            assert "<!-- clause: lease.notices-and-disputes@0.1.0 -->" not in rendered

    def test_lease_renderer_omits_a_non_applicable_clause(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            data = workspace / "no-rent-update.yaml"
            output = workspace / "lease.pdf"
            _ = data.write_text(
                COMPLETE_DATA.read_text(encoding="utf-8").replace(
                    "    monthly_rent: 9999\n",
                    "    monthly_rent: 9999\n"
                    "    rent_update:\n"
                    "      enabled: false\n",
                    1,
                ),
                encoding="utf-8",
            )

            # When
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "--script",
                    str(RENDERER),
                    str(TEMPLATE),
                    str(data),
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Then
            assert result.returncode == 0, result.stdout + result.stderr
            rendered = output.with_suffix(".md").read_text(encoding="utf-8")
            selection = _Selection.model_validate(
                yaml.safe_load(
                    output.with_suffix(".selection.yaml").read_text(
                        encoding="utf-8",
                    ),
                ),
            )
            assert "lease.rent-update@0.1.0" not in selection.candidate_clauses
            assert selection.not_applicable_clauses == (
                "lease.rent-update@0.1.0",
            )
            assert "<!-- clause: lease.rent-update@0.1.0 -->" not in rendered


if __name__ == "__main__":
    _ = unittest.main()

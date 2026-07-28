from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "manage-document-projects"
PACKAGE = SKILL / "assets" / "project-types" / "residential-lease"
SELECTOR = SKILL / "scripts" / "select_clauses.py"
COMPLETE_DATA = PACKAGE / "examples" / "minimal-project.yaml"
INCOMPLETE_DATA = PACKAGE / "examples" / "minimal-core-project.yaml"


class _BlockedClause(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    reasons: tuple[str, ...]
    missing_data_paths: tuple[str, ...] = ()


class _Provenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    data_sha256: str
    schema_sha256: str
    catalog_sha256: str
    jurisdiction_sha256: str


class _Selection(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_clauses: tuple[str, ...]
    blocked_clauses: tuple[_BlockedClause, ...]
    not_applicable_clauses: tuple[str, ...]
    provenance: _Provenance


def _run_selector(
    data: Path,
    workspace: Path,
    output_name: str = "selection.yaml",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    request = workspace / f"{output_name}.request.yaml"
    output = workspace / output_name
    _ = request.write_text(
        "request_version: \"0.1.0\"\n"
        f"project_type: {PACKAGE / 'project-type.yaml'}\n"
        f"data: {data}\n"
        "document: lease\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["uv", "run", "--script", str(SELECTOR), str(request), str(output)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result, output


def _read_selection(path: Path) -> _Selection:
    return _Selection.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_selects_every_data_ready_clause_and_blocks_legal_review() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)

        # When
        result, output = _run_selector(COMPLETE_DATA, workspace)

        # Then
        assert result.returncode == 0, result.stdout + result.stderr
        selection = _read_selection(output)
        assert len(selection.candidate_clauses) == 9
        assert "lease.rent-update@0.1.0" in selection.candidate_clauses
        assert selection.not_applicable_clauses == ()
        assert selection.blocked_clauses == (
            _BlockedClause(
                id="lease.notices-and-disputes@0.1.0",
                reasons=("legal-review-required",),
            ),
        )
        assert all(
            len(digest) == 64
            for digest in (
                selection.provenance.data_sha256,
                selection.provenance.schema_sha256,
                selection.provenance.catalog_sha256,
                selection.provenance.jurisdiction_sha256,
            )
        )


def test_reports_missing_paths_for_an_incomplete_draft() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)

        # When
        result, output = _run_selector(INCOMPLETE_DATA, workspace)

        # Then
        assert result.returncode == 0, result.stdout + result.stderr
        selection = _read_selection(output)
        assert len(selection.candidate_clauses) == 4
        blocked_by_id = {clause.id: clause for clause in selection.blocked_clauses}
        assert len(blocked_by_id) == 6
        assert blocked_by_id["lease.rent-update@0.1.0"].missing_data_paths == (
            "operation.lease.rent_update.enabled",
        )
        assert blocked_by_id[
            "lease.conservation-and-works@0.1.0"
        ].missing_data_paths == ("operation.lease.works_policy",)
        assert blocked_by_id["lease.notices-and-disputes@0.1.0"].reasons == (
            "legal-review-required",
        )


def test_marks_disabled_rent_update_as_not_applicable() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        data = workspace / "no-rent-update.yaml"
        source = COMPLETE_DATA.read_text(encoding="utf-8")
        _ = data.write_text(
            source.replace(
                "    monthly_rent: 9999\n",
                "    monthly_rent: 9999\n"
                "    rent_update:\n"
                "      enabled: false\n",
                1,
            ),
            encoding="utf-8",
        )

        # When
        result, output = _run_selector(data, workspace)

        # Then
        assert result.returncode == 0, result.stdout + result.stderr
        selection = _read_selection(output)
        assert "lease.rent-update@0.1.0" not in selection.candidate_clauses
        assert selection.not_applicable_clauses == ("lease.rent-update@0.1.0",)


def test_same_inputs_produce_identical_selection_bytes() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)

        # When
        first_result, first_output = _run_selector(
            COMPLETE_DATA,
            workspace,
            "first.yaml",
        )
        second_result, second_output = _run_selector(
            COMPLETE_DATA,
            workspace,
            "second.yaml",
        )

        # Then
        assert first_result.returncode == 0, first_result.stdout + first_result.stderr
        assert second_result.returncode == 0, second_result.stdout + second_result.stderr
        assert first_output.read_bytes() == second_output.read_bytes()


def test_rejects_enabled_rent_update_with_an_invalid_index() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        data = workspace / "invalid-rent-update.yaml"
        _ = data.write_text(
            COMPLETE_DATA.read_text(encoding="utf-8").replace(
                "    monthly_rent: 9999\n",
                "    monthly_rent: 9999\n"
                "    rent_update:\n"
                "      enabled: true\n"
                "      reference_index: null\n",
                1,
            ),
            encoding="utf-8",
        )

        # When
        result, output = _run_selector(data, workspace)

        # Then
        assert result.returncode != 0
        assert "operation.lease.rent_update" in result.stdout + result.stderr
        assert "Traceback" not in result.stdout + result.stderr
        assert not output.exists()

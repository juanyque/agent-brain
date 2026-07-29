from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from document_project_workspace import workspace_environment

ROOT = Path(__file__).resolve().parents[1]
RENDERER = (
    ROOT / "skills" / "manage-document-projects" / "scripts" / "render_document.py"
)
PACKAGE = (
    ROOT
    / "skills"
    / "manage-document-projects"
    / "assets"
    / "project-types"
    / "residential-lease"
)


def test_renderer_reports_missing_document_data_without_partial_outputs() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        data = workspace / "project-data.yaml"
        output = workspace / "reservation.pdf"
        _ = output.write_bytes(b"%PDF-existing")
        _ = data.write_text(
            json.dumps(
                {
                    "schema_version": "0.2.0",
                    "project": {
                        "id": "incomplete-residential-lease",
                        "type": "residential-lease",
                        "type_version": "0.2.0",
                        "jurisdiction": "es-md-madrid",
                        "effective_date": None,
                        "data_revision": "0",
                        "defaults_profile": "residential-standard",
                    },
                    "property": {
                        "id": "incomplete-property",
                        "address": {
                            "full_text": "Calle de Prueba 1",
                            "postal_code": None,
                            "municipality": "Madrid",
                            "province": "Madrid",
                            "country_code": "ES",
                        },
                        "intended_use": "habitual-residence",
                    },
                    "parties": {
                        "landlords": [],
                        "tenants": [],
                    },
                    "operation": {
                        "currency": "EUR",
                        "reservation": None,
                        "lease": None,
                    },
                    "inventory": None,
                },
                ensure_ascii=False,
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
                str(PACKAGE / "templates" / "reservation.md.j2"),
                str(data),
                str(output),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=workspace_environment(workspace),
        )

        # Then
        diagnostic = result.stdout + result.stderr
        assert result.returncode == 2
        assert "report_version: 0.1.0" in diagnostic
        assert "document: reservation" in diagnostic
        assert "resolution: user-required" in diagnostic
        assert "project.effective_date" in diagnostic
        assert "property.address.postal_code" in diagnostic
        assert "parties.landlords" in diagnostic
        assert "parties.tenants" in diagnostic
        assert "operation.reservation.agreement_date" in diagnostic
        assert "operation.lease.monthly_rent" in diagnostic
        assert "Traceback" not in diagnostic
        assert "KeyError" not in diagnostic
        assert output.read_bytes() == b"%PDF-existing"
        assert not output.with_suffix(".md").exists()
        assert not output.with_suffix(".selection.yaml").exists()
        assert not output.with_suffix(".provenance.yaml").exists()

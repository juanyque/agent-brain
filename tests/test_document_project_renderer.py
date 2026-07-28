from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERER = (
    ROOT / "skills" / "manage-document-projects" / "scripts" / "render_document.py"
)
RESIDENTIAL_LEASE = (
    ROOT
    / "skills"
    / "manage-document-projects"
    / "assets"
    / "project-types"
    / "residential-lease"
)
RESIDENTIAL_DOCUMENT_TYPES = ("reservation", "lease", "inventory", "access-license")


class DocumentProjectRendererTests(unittest.TestCase):
    def test_reservation_example_preserves_the_agreed_2025_concepts(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            template = RESIDENTIAL_LEASE / "templates" / "reservation.md.j2"
            data = RESIDENTIAL_LEASE / "examples" / "minimal-project.yaml"
            output = workspace / "reservation.pdf"

            # When
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "--script",
                    str(RENDERER),
                    str(template),
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
            expected_concepts = (
                "capacidad legal suficiente",
                "arrendatarios solidarios",
                "[ ] **Entrega en metálico en este acto.**",
                "[x] **Transferencia bancaria.**",
                "2 días laborables",
                "uso exclusivo como vivienda habitual",
                "13/02/2026",
                "cinco años",
                "9.999,00 €",
                "primeros cinco días",
                "Seguro de impago",
                "se encuentra pendiente",
                "perderá el importe de la reserva",
                "devolverá íntegramente",
            )
            for concept in expected_concepts:
                with self.subTest(concept=concept):
                    assert concept in rendered
            assert "Fecha efectiva de pago" not in rendered
            assert "Fecha de decisión" not in rendered
            assert "obtenida el" not in rendered

    def test_bundled_residential_templates_create_printable_outputs(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            data = RESIDENTIAL_LEASE / "examples" / "minimal-project.yaml"

            # When
            results = tuple(
                subprocess.run(
                    [
                        "uv",
                        "run",
                        "--script",
                        str(RENDERER),
                        str(
                            RESIDENTIAL_LEASE / "templates" / f"{document_type}.md.j2",
                        ),
                        str(data),
                        str(workspace / f"{document_type}.pdf"),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                for document_type in RESIDENTIAL_DOCUMENT_TYPES
            )

            # Then
            for document_type, result in zip(
                RESIDENTIAL_DOCUMENT_TYPES,
                results,
                strict=True,
            ):
                with self.subTest(document_type=document_type):
                    markdown = workspace / f"{document_type}.md"
                    pdf = workspace / f"{document_type}.pdf"
                    assert result.returncode == 0, result.stdout + result.stderr
                    rendered = markdown.read_text(encoding="utf-8")
                    assert f"document_type: {document_type}" in rendered
                    assert "{{" not in rendered
                    assert "{%" not in rendered
                    assert pdf.read_bytes().startswith(b"%PDF-")

    def test_bundled_renderer_rejects_data_that_violates_package_schema(
        self,
    ) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            template = RESIDENTIAL_LEASE / "templates" / "reservation.md.j2"
            source_data = RESIDENTIAL_LEASE / "examples" / "minimal-project.yaml"
            invalid_data = workspace / "invalid-project.yaml"
            output = workspace / "reservation.pdf"
            _ = invalid_data.write_text(
                source_data.read_text(encoding="utf-8").replace(
                    "id: synthetic-residential-lease",
                    "id: INVALID PROJECT ID",
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
                    str(template),
                    str(invalid_data),
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Then
            assert result.returncode != 0
            assert "$.project.id" in result.stdout + result.stderr
            assert "Traceback" not in result.stdout + result.stderr
            assert "TypeError" not in result.stdout + result.stderr
            assert not output.exists()
            assert not output.with_suffix(".md").exists()

    def test_renderer_creates_markdown_and_pdf_from_yaml_data(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            template = workspace / "reserva.md.j2"
            data = workspace / "datos.yaml"
            output = workspace / "reserva.pdf"
            _ = template.write_text(
                "# Contrato de {{ contrato.tipo }}\n\n"
                "Fecha: {{ contrato.fecha }}.\n\n"
                "Arrendatario: **{{ arrendatario.nombre }}**.\n",
                encoding="utf-8",
            )
            _ = data.write_text(
                "contrato:\n"
                "  tipo: reserva\n"
                "  fecha: 2026-07-23\n"
                "arrendatario:\n"
                "  nombre: Alex Demo\n",
                encoding="utf-8",
            )

            # When
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "--script",
                    str(RENDERER),
                    str(template),
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
            assert (
                output.with_suffix(".md").read_text(
                    encoding="utf-8",
                )
                == "# Contrato de reserva\n\n"
                "Fecha: 2026-07-23.\n\n"
                "Arrendatario: **Alex Demo**.\n"
            )
            assert output.read_bytes().startswith(b"%PDF-")

    def test_renderer_rejects_an_unresolved_template_variable(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            template = workspace / "alquiler.md.j2"
            data = workspace / "datos.yaml"
            output = workspace / "alquiler.pdf"
            _ = template.write_text(
                "# Contrato\n\nIBAN: {{ arrendador.iban }}\n",
                encoding="utf-8",
            )
            _ = data.write_text(
                "arrendador:\n  nombre: Alex Demo\n",
                encoding="utf-8",
            )

            # When
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "--script",
                    str(RENDERER),
                    str(template),
                    str(data),
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Then
            assert result.returncode != 0
            assert "iban" in result.stdout + result.stderr
            assert not output.exists()
            assert not output.with_suffix(".md").exists()

    def test_renderer_preserves_an_existing_pdf(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            template = workspace / "reserva.md.j2"
            data = workspace / "datos.yaml"
            output = workspace / "reserva.pdf"
            _ = template.write_text("# {{ titulo }}\n", encoding="utf-8")
            _ = data.write_text("titulo: Documento nuevo\n", encoding="utf-8")
            _ = output.write_bytes(b"%PDF-existing")

            # When
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "--script",
                    str(RENDERER),
                    str(template),
                    str(data),
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Then
            assert result.returncode != 0
            assert "already exists" in result.stdout + result.stderr
            assert "Traceback" not in result.stdout + result.stderr
            assert "TypeError" not in result.stdout + result.stderr
            assert output.read_bytes() == b"%PDF-existing"


if __name__ == "__main__":
    _ = unittest.main()

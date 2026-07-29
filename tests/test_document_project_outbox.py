from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from document_project_workspace import workspace_environment

ROOT = Path(__file__).resolve().parents[1]
RENDERER = (
    ROOT / "skills" / "manage-document-projects" / "scripts" / "render_document.py"
)


def _run_renderer(
    template: Path,
    data: Path,
    output: Path,
    brain: Path,
    *options: str,
) -> subprocess.CompletedProcess[str]:
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
        env=workspace_environment(
            brain,
            deliverables=Path("OUTBOX"),
            git_visibility="required",
        ),
    )


class DocumentProjectOutboxTests(unittest.TestCase):
    def test_brain_render_requires_pdf_under_outbox(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            template = brain / "template.md.j2"
            data = brain / "data.yaml"
            output = brain / "WIP" / "preview.pdf"
            _ = template.write_text("# {{ title }}\n", encoding="utf-8")
            _ = data.write_text("title: Preview\n", encoding="utf-8")

            # When
            result = _run_renderer(template, data, output, brain)

            # Then
            assert result.returncode != 0
            assert "OUTBOX" in result.stdout + result.stderr
            assert not output.exists()

    def test_brain_render_rejects_an_ignored_outbox(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            template = brain / "template.md.j2"
            data = brain / "data.yaml"
            output = brain / "OUTBOX" / "preview.pdf"
            _ = template.write_text("# {{ title }}\n", encoding="utf-8")
            _ = data.write_text("title: Preview\n", encoding="utf-8")
            _ = (brain / ".gitignore").write_text("OUTBOX/\n", encoding="utf-8")
            _ = subprocess.run(
                ["git", "init", "--quiet", str(brain)],
                check=True,
            )

            # When
            result = _run_renderer(template, data, output, brain)

            # Then
            assert result.returncode != 0
            assert "ignored by Git" in result.stdout + result.stderr
            assert not output.exists()

    def test_replace_updates_stable_outbox_output_after_preflight(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            template = brain / "template.md.j2"
            data = brain / "data.yaml"
            output = brain / "OUTBOX" / "lease" / "reservation.pdf"
            markdown = brain / "WIP" / "lease" / "documents" / "reservation.md"
            _ = template.write_text("# {{ title }}\n", encoding="utf-8")
            _ = data.write_text("title: First draft\n", encoding="utf-8")
            _ = subprocess.run(
                ["git", "init", "--quiet", str(brain)],
                check=True,
            )
            first = _run_renderer(
                template,
                data,
                output,
                brain,
                "--markdown-output",
                str(markdown),
            )
            assert first.returncode == 0, first.stdout + first.stderr
            _ = data.write_text("title: Revised draft\n", encoding="utf-8")

            # When
            preflight = _run_renderer(
                template,
                data,
                output,
                brain,
                "--markdown-output",
                str(markdown),
            )
            replaced = _run_renderer(
                template,
                data,
                output,
                brain,
                "--markdown-output",
                str(markdown),
                "--replace",
            )

            # Then
            assert preflight.returncode != 0
            assert "untracked" in preflight.stdout + preflight.stderr
            assert replaced.returncode == 0, replaced.stdout + replaced.stderr
            assert markdown.read_text(encoding="utf-8") == "# Revised draft\n"
            assert output.read_bytes().startswith(b"%PDF-")
            assert not tuple(output.parent.glob("*v[0-9]*"))

    def test_preflight_distinguishes_committed_and_modified_outputs(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            template = brain / "template.md.j2"
            data = brain / "data.yaml"
            output = brain / "OUTBOX" / "preview.pdf"
            _ = template.write_text("# {{ title }}\n", encoding="utf-8")
            _ = data.write_text("title: Preview\n", encoding="utf-8")
            output.parent.mkdir(parents=True)
            _ = output.write_bytes(b"%PDF-committed")
            _ = subprocess.run(
                ["git", "init", "--quiet", str(brain)],
                check=True,
            )
            _ = subprocess.run(
                ["git", "-C", str(brain), "add", "OUTBOX/preview.pdf"],
                check=True,
            )
            _ = subprocess.run(
                [
                    "git",
                    "-C",
                    str(brain),
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "fixture",
                ],
                check=True,
            )

            # When
            committed = _run_renderer(template, data, output, brain)
            _ = output.write_bytes(b"%PDF-modified")
            modified = _run_renderer(template, data, output, brain)

            # Then
            assert committed.returncode != 0
            assert "committed" in committed.stdout + committed.stderr
            assert modified.returncode != 0
            assert "modified" in modified.stdout + modified.stderr


if __name__ == "__main__":
    _ = unittest.main()

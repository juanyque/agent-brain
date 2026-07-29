from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "manage-document-projects"
DOCTOR = SKILL_DIR / "scripts" / "doctor.sh"
SETUP = SKILL_DIR / "scripts" / "setup.sh"


def write_tool(directory: Path, name: str, version: str) -> None:
    path = directory / name
    path.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' '{version}'\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def write_uv_tool(directory: Path) -> None:
    real_uv = shutil.which("uv")
    assert real_uv is not None
    path = directory / "uv"
    path.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${1:-}" == "run" ]]; then\n'
        f"  exec '{real_uv}' \"$@\"\n"
        "fi\n"
        "printf '%s\\n' 'uv 0.8.0'\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


class DocumentProjectSetupTests(unittest.TestCase):
    def test_doctor_reports_ready_when_required_tools_exist(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            probe = Path(raw)
            write_tool(probe, "python3", "Python 3.14.6")
            write_tool(probe, "uv", "uv 0.8.0")
            write_tool(probe, "pandoc", "pandoc 3.10")
            write_tool(probe, "soffice", "LibreOffice 26.2.4.2")
            write_tool(probe, "weasyprint", "WeasyPrint 69.0")
            write_tool(probe, "ssh-keygen", "OpenSSH_10.0")

            # When
            result = subprocess.run(
                ["bash", str(DOCTOR)],
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "DOCUMENT_PROJECT_PROBE_PATH": str(probe),
                },
            )

            # Then
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("manage-document-projects doctor: READY", result.stdout)
            self.assertIn("CSS_PDF=yes", result.stdout)
            self.assertIn("OFFICE_PDF=yes", result.stdout)
            self.assertIn("AUTHENTIC_RELEASE=yes", result.stdout)

    def test_doctor_fails_when_pandoc_is_missing(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            probe = Path(raw)
            write_tool(probe, "python3", "Python 3.14.6")
            write_tool(probe, "uv", "uv 0.8.0")
            write_tool(probe, "soffice", "LibreOffice 26.2.4.2")

            # When
            result = subprocess.run(
                ["bash", str(DOCTOR)],
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "DOCUMENT_PROJECT_PROBE_PATH": str(probe),
                },
            )

            # Then
            self.assertEqual(result.returncode, 1)
            self.assertIn("FAIL  pandoc", result.stdout)
            self.assertIn("manage-document-projects doctor: NEEDS SETUP", result.stdout)
            self.assertIn("CSS_PDF=no", result.stdout)

    def test_setup_dry_run_calls_doctor_without_installing(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            probe = root / "probe"
            home = root / "home"
            marker = root / "brew-called"
            probe.mkdir()
            (home / ".agents").mkdir(parents=True)
            write_tool(probe, "python3", "Python 3.14.6")
            write_uv_tool(probe)
            write_tool(probe, "soffice", "LibreOffice 26.2.4.2")
            brew = probe / "brew"
            brew.write_text(
                f"#!/usr/bin/env bash\ntouch '{marker}'\n",
                encoding="utf-8",
            )
            brew.chmod(0o755)

            # When
            result = subprocess.run(
                [
                    "bash",
                    str(SETUP),
                    "--non-interactive",
                    "--workspace-root",
                    str(root / "workspace"),
                ],
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "DOCUMENT_PROJECT_CONFIG_PATH": str(root / "config.yaml"),
                    "DOCUMENT_PROJECT_PROBE_PATH": str(probe),
                    "HOME": str(home),
                    "PATH": f"{probe}:/usr/bin:/bin",
                    "SKILL_LINK_LOG_FILE": str(root / "skill-link.log"),
                },
            )

            # Then
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("manage-document-projects doctor: NEEDS SETUP", result.stdout)
            self.assertIn("PLAN    brew install pandoc", result.stdout)
            self.assertIn("SKIP    weasyprint declined in configuration", result.stdout)
            self.assertIn("dry-run", result.stdout)
            self.assertFalse(marker.exists())

    def test_setup_plans_uv_when_renderer_runtime_is_missing(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            probe = root / "probe"
            home = root / "home"
            probe.mkdir()
            home.mkdir()
            write_tool(probe, "python3", "Python 3.14.6")
            write_tool(probe, "pandoc", "pandoc 3.10")
            write_tool(probe, "soffice", "LibreOffice 26.2.4.2")
            write_tool(probe, "weasyprint", "WeasyPrint 69.0")
            write_tool(probe, "brew", "Homebrew 5.0.0")

            # When
            result = subprocess.run(
                ["bash", str(SETUP)],
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "DOCUMENT_PROJECT_PROBE_PATH": str(probe),
                    "HOME": str(home),
                    "PATH": f"{probe}:/usr/bin:/bin",
                    "SKILL_LINK_LOG_FILE": str(root / "skill-link.log"),
                },
            )

            # Then
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PLAN    brew install uv", result.stdout)

    def test_setup_persists_workspace_and_optional_tools_in_one_config(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            probe = root / "probe"
            home = root / "home"
            workspace = root / "workspace"
            config = root / "config.yaml"
            probe.mkdir()
            (home / ".agents").mkdir(parents=True)
            write_tool(probe, "python3", "Python 3.14.6")
            write_uv_tool(probe)
            write_tool(probe, "pandoc", "pandoc 3.10")
            write_tool(probe, "weasyprint", "WeasyPrint 69.0")
            write_tool(probe, "ssh-keygen", "OpenSSH_10.0")

            # When
            result = subprocess.run(
                [
                    "bash",
                    str(SETUP),
                    "--apply",
                    "--non-interactive",
                    "--workspace-root",
                    str(workspace),
                    "--projects-dir",
                    "projects",
                    "--deliverables-dir",
                    "exports",
                    "--incoming-dir",
                    "inbox",
                    "--with-weasyprint",
                    "--without-libreoffice",
                    "--with-openssh",
                ],
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "DOCUMENT_PROJECT_CONFIG_PATH": str(config),
                    "DOCUMENT_PROJECT_PROBE_PATH": str(probe),
                    "HOME": str(home),
                    "PATH": f"{probe}:/usr/bin:/bin",
                    "SKILL_LINK_LOG_FILE": str(root / "skill-link.log"),
                },
            )

            # Then
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            configured = yaml.safe_load(config.read_text(encoding="utf-8"))
            self.assertEqual(configured["default_profile"], "default")
            self.assertEqual(
                configured["optional_tools"],
                {
                    "weasyprint": "install",
                    "libreoffice": "decline",
                    "openssh": "install",
                },
            )
            self.assertEqual(
                configured["profiles"]["default"]["workspace_root"],
                str(workspace.resolve()),
            )
            self.assertTrue((workspace / "projects").is_dir())
            self.assertTrue((workspace / "exports").is_dir())
            self.assertTrue((workspace / "inbox").is_dir())


if __name__ == "__main__":
    unittest.main()

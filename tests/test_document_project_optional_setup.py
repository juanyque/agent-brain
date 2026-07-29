from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "skills" / "manage-document-projects" / "scripts" / "setup.sh"


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


def base_environment(root: Path, probe: Path) -> dict[str, str]:
    home = root / "home"
    (home / ".agents").mkdir(parents=True)
    return {
        **os.environ,
        "DOCUMENT_PROJECT_CONFIG_PATH": str(root / "config.yaml"),
        "DOCUMENT_PROJECT_PROBE_PATH": str(probe),
        "DOCUMENT_PROJECT_WORKSPACE_ROOT": str(root / "workspace"),
        "HOME": str(home),
        "PATH": f"{probe}:/usr/bin:/bin",
        "SKILL_LINK_LOG_FILE": str(root / "skill-link.log"),
    }


class DocumentProjectOptionalSetupTests(unittest.TestCase):
    def test_apply_installs_selected_optional_only_once(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            probe = root / "probe"
            probe.mkdir()
            write_tool(probe, "python3", "Python 3.14.6")
            write_uv_tool(probe)
            write_tool(probe, "pandoc", "pandoc 3.10")
            log = root / "brew.log"
            brew = probe / "brew"
            brew.write_text(
                "#!/usr/bin/env bash\n"
                'printf \'%s\\n\' "$*" >> "$BREW_LOG"\n'
                'if [[ "$*" == *weasyprint* ]]; then\n'
                "  printf '#!/usr/bin/env bash\\nprintf \"WeasyPrint 69.0\\\\n\"\\n'"
                ' > "$DOCUMENT_PROJECT_PROBE_PATH/weasyprint"\n'
                '  chmod +x "$DOCUMENT_PROJECT_PROBE_PATH/weasyprint"\n'
                "fi\n",
                encoding="utf-8",
            )
            brew.chmod(0o755)
            environment = {
                **base_environment(root, probe),
                "BREW_LOG": str(log),
            }

            # When
            first = subprocess.run(
                [
                    "bash",
                    str(SETUP),
                    "--apply",
                    "--non-interactive",
                    "--with-weasyprint",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            second = subprocess.run(
                [
                    "bash",
                    str(SETUP),
                    "--apply",
                    "--non-interactive",
                    "--with-weasyprint",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            # Then
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(
                log.read_text(encoding="utf-8").splitlines(), ["install weasyprint"]
            )
            self.assertIn("SKIP    weasyprint already installed", second.stdout)

    def test_libreoffice_is_a_separate_optional_cask(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            probe = root / "probe"
            probe.mkdir()
            write_tool(probe, "python3", "Python 3.14.6")
            write_uv_tool(probe)
            write_tool(probe, "pandoc", "pandoc 3.10")
            write_tool(probe, "brew", "Homebrew 5.0.0")

            # When
            result = subprocess.run(
                ["bash", str(SETUP), "--with-libreoffice"],
                check=False,
                capture_output=True,
                text=True,
                env=base_environment(root, probe),
            )

            # Then
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PLAN    brew install --cask libreoffice", result.stdout)
            self.assertNotIn("brew install weasyprint", result.stdout)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_BOOTSTRAP = REPO_ROOT / "bootstrap-zero.sh"


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )


def run_ensure_repo(script: Path, canonical: Path, repo_url: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; CANONICAL="$2"; [[ -n "${3:-}" ]] && REPO_URL="$3"; ensure_repo',
            "_",
            str(script),
            str(canonical),
            *( [repo_url] if repo_url else [] ),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


class BootstrapRootUpdateTests(unittest.TestCase):
    def _remote_with_second_commit(self, root: Path) -> tuple[Path, Path]:
        source = root / "source"
        source.mkdir()
        git("init", "-q", "-b", "main", cwd=source)
        (source / "README.md").write_text("v1\n", encoding="utf-8")
        git("add", ".", cwd=source)
        git(
            "-c",
            "user.email=fixture@example.com",
            "-c",
            "user.name=fixture",
            "commit",
            "-qm",
            "v1",
            cwd=source,
        )
        remote = root / "remote.git"
        git("clone", "-q", "--bare", str(source), str(remote))
        (source / "README.md").write_text("v2\n", encoding="utf-8")
        git("add", ".", cwd=source)
        git(
            "-c",
            "user.email=fixture@example.com",
            "-c",
            "user.name=fixture",
            "commit",
            "-qm",
            "v2",
            cwd=source,
        )
        git("push", "-q", str(remote), "main", cwd=source)
        return remote, source

    def test_update_unshallows_and_fast_forwards(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            remote, source = self._remote_with_second_commit(root)
            canonical = root / "canon"
            git("clone", "-q", "--depth", "1", f"file://{remote}", str(canonical))
            self.assertEqual(
                git("rev-parse", "--is-shallow-repository", cwd=canonical).stdout.strip(),
                "true",
            )

            result = run_ensure_repo(ROOT_BOOTSTRAP, canonical)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("fetching full history", result.stdout + result.stderr)
            self.assertIn("OK: agent-brain updated", result.stdout + result.stderr)
            self.assertEqual(
                git("rev-parse", "--is-shallow-repository", cwd=canonical).stdout.strip(),
                "false",
            )
            local_head = git("rev-parse", "HEAD", cwd=canonical).stdout.strip()
            remote_head = git("rev-parse", "HEAD", cwd=source).stdout.strip()
            self.assertEqual(local_head, remote_head)

    def test_update_failure_is_explicit_and_non_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            remote, source = self._remote_with_second_commit(root)
            canonical = root / "canon"
            git("clone", "-q", "--depth", "1", f"file://{remote}", str(canonical))
            (canonical / "local-change").write_text("divergence\n", encoding="utf-8")
            git("add", ".", cwd=canonical)
            git(
                "-c",
                "user.email=fixture@example.com",
                "-c",
                "user.name=fixture",
                "commit",
                "-qm",
                "local divergence",
                cwd=canonical,
            )
            (source / "README.md").write_text("v3\n", encoding="utf-8")
            git("add", ".", cwd=source)
            git(
                "-c",
                "user.email=fixture@example.com",
                "-c",
                "user.name=fixture",
                "commit",
                "-qm",
                "v3",
                cwd=source,
            )
            git("push", "-q", str(remote), "main", cwd=source)

            result = run_ensure_repo(ROOT_BOOTSTRAP, canonical)

            self.assertEqual(result.returncode, 0, result.stderr)
            combined = result.stdout + result.stderr
            self.assertIn("update failed", combined)
            self.assertIn("Recover with one of", combined)
            self.assertIn("reset --hard origin/main", combined)
            self.assertNotIn("OK: agent-brain updated", combined)

    def test_first_clone_via_repo_url_and_path_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            remote, source = self._remote_with_second_commit(root)
            canonical = root / "canon dir"

            result = run_ensure_repo(ROOT_BOOTSTRAP, canonical, repo_url=f"file://{remote}")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("OK: agent-brain cloned", result.stdout + result.stderr)
            local_head = git("rev-parse", "HEAD", cwd=canonical).stdout.strip()
            remote_head = git("rev-parse", "HEAD", cwd=source).stdout.strip()
            self.assertEqual(local_head, remote_head)

    def test_sourcing_the_script_defines_functions_without_cloning(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            env = os.environ.copy()
            env["AGENT_BRAIN_HOME"] = str(Path(raw) / "absent")
            result = subprocess.run(
                ["bash", "-c", 'source "$1"; declare -F ensure_repo', "_", str(ROOT_BOOTSTRAP)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ensure_repo", result.stdout)


if __name__ == "__main__":
    unittest.main()

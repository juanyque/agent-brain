from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_SCRIPTS = (
    Path(__file__).resolve().parents[1] / "skills" / "push-gate" / "scripts"
)
sys.path.insert(0, str(SKILL_SCRIPTS))

from pre_push_audit import (  # noqa: E402
    CONFIG_SCHEMA,
    Finding,
    GateConfig,
    audit_diff,
    main,
    redact,
)

TOKENS = json.loads(
    (
        Path(__file__).resolve().parent
        / "fixtures"
        / "push-gate"
        / "synthetic-tokens.json"
    ).read_text(encoding="utf-8")
)

FAKE_AWS_KEY = TOKENS["aws_key"]
FAKE_ASIA_KEY = TOKENS["asia_key"]
FAKE_GHP = TOKENS["ghp"]
FAKE_GHS = TOKENS["ghs"]
FAKE_XOXC = TOKENS["xoxc"]
FAKE_XOXE = TOKENS["xoxe"]
FAKE_XAPP = TOKENS["xapp"]
FAKE_JWT = TOKENS["jwt"]
FAKE_DNI = TOKENS["dni"]
FAKE_DNI_HYPHEN = TOKENS["dni_hyphen"]
FAKE_NIE = TOKENS["nie"]
FAKE_IBAN = TOKENS["iban"]
FAKE_PHONE = TOKENS["phone"]
FAKE_OWNER = "/Users/somebody/workspace/repo"


def diff_for(path: str, added_lines: list[str]) -> dict[str, list[tuple[int, str]]]:
    return {path: [(i + 1, line) for i, line in enumerate(added_lines)]}


def kinds(findings: list[Finding]) -> set[str]:
    return {f.kind for f in findings}


class RedactTests(unittest.TestCase):
    def test_long_value_is_truncated(self) -> None:
        redacted = redact("AKIAIOSFODNN7EXAMPLE")
        self.assertTrue(redacted.startswith("AKIA"))
        self.assertNotIn("EXAMPLE", redacted)

    def test_short_value_is_masked(self) -> None:
        self.assertEqual(redact("abc"), "a…")


class DetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = GateConfig({})

    def test_aws_and_asia_keys_are_detected(self) -> None:
        findings = audit_diff(
            diff_for("src/a.py", [f'k1="{FAKE_AWS_KEY}" k2="{FAKE_ASIA_KEY}"']),
            [("A", "src/a.py", None)],
            self.config,
        )
        self.assertIn("aws-access-key-id", kinds(findings))

    def test_github_token_family_is_detected(self) -> None:
        findings = audit_diff(
            diff_for("src/a.py", [f"a={FAKE_GHP} b={FAKE_GHS}"]),
            [("A", "src/a.py", None)],
            self.config,
        )
        self.assertIn("github-pat-classic", kinds(findings))
        self.assertIn("github-token-family", kinds(findings))

    def test_slack_and_jwt_shapes_are_detected(self) -> None:
        findings = audit_diff(
            diff_for("src/a.py", [f"s={FAKE_XOXC} e={FAKE_XOXE} a={FAKE_XAPP} j={FAKE_JWT}"]),
            [("A", "src/a.py", None)],
            self.config,
        )
        self.assertIn("slack-token", kinds(findings))
        self.assertIn("jwt", kinds(findings))
        slack_matches = [f.redacted for f in findings if f.kind == "slack-token"]
        self.assertEqual(len(slack_matches), 3)

    def test_filename_pii_with_underscores_is_detected(self) -> None:
        findings = audit_diff(
            {}, [("A", f"docs/{FAKE_DNI}_report.md", None)], self.config
        )
        self.assertIn("dni-nif-in-path", kinds(findings))
        findings = audit_diff(
            {}, [("A", f"docs/{FAKE_NIE}_scan.pdf", None)], self.config
        )
        self.assertIn("nie-in-path", kinds(findings))

    def test_config_field_types_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            GateConfig({"allow_paths": "tests/"})
        with self.assertRaises(ValueError):
            GateConfig({"allow_strings": [""]})
        with self.assertRaises(ValueError):
            GateConfig({"protected_paths": [42]})

    def test_config_non_object_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            bad = Path(raw) / "push-gate.json"
            bad.write_text('["not", "an", "object"]')
            with self.assertRaises(ValueError):
                GateConfig.load(bad)

    def test_client_secret_assignment_is_detected(self) -> None:
        findings = audit_diff(
            diff_for(
                "src/conf.py",
                ["client_secret = " + "d" * 24, "unquoted_token: " + "e" * 21],
            ),
            [("A", "src/conf.py", None)],
            self.config,
        )
        self.assertIn("assigned-secret-literal", kinds(findings))

    def test_spanish_pii_variants_are_detected(self) -> None:
        findings = audit_diff(
            diff_for(
                "docs/e.md",
                [
                    f"DNI {FAKE_DNI} y {FAKE_DNI_HYPHEN}, NIE {FAKE_NIE}, "
                    f"IBAN {FAKE_IBAN}, tel {FAKE_PHONE}"
                ],
            ),
            [("A", "docs/e.md", None)],
            self.config,
        )
        self.assertIn("dni-nif", kinds(findings))
        self.assertIn("nie", kinds(findings))
        self.assertIn("iban-es", kinds(findings))
        self.assertIn("phone-es", kinds(findings))

    def test_owner_path_is_detected(self) -> None:
        findings = audit_diff(
            diff_for("README.md", [f"run {FAKE_OWNER}/bin/tool"]),
            [("A", "README.md", None)],
            self.config,
        )
        self.assertIn("home-users-path", kinds(findings))

    def test_fixture_paths_do_not_trigger_owner_path(self) -> None:
        findings = audit_diff(
            diff_for("README.md", ["brain_root: /fixture/brain"]),
            [("A", "README.md", None)],
            self.config,
        )
        self.assertNotIn("home-users-path", kinds(findings))

    def test_generic_doc_example_usernames_are_exempt(self) -> None:
        findings = audit_diff(
            diff_for("docs/usage.md", ["Examples: `/Users/foo/bar` maps to X"]),
            [("A", "docs/usage.md", None)],
            self.config,
        )
        self.assertNotIn("home-users-path", kinds(findings))

    def test_date_prefixed_filenames_do_not_trigger_in_path_pii(self) -> None:
        findings = audit_diff(
            {}, [("A", "WIP/evidence/20260731-codex-start.md", None)], self.config
        )
        self.assertNotIn("dni-nif-in-path", kinds(findings))

    def test_changed_filenames_are_scanned_themselves(self) -> None:
        findings = audit_diff(
            {}, [("A", f"docs/{FAKE_DNI}-informe.md", None)], self.config
        )
        self.assertIn("dni-nif-in-path", kinds(findings))
        findings = audit_diff(
            {}, [("A", f"notes/{FAKE_OWNER.strip('/')}/x.md", None)], self.config
        )
        self.assertIn("home-users-path-in-path", kinds(findings))

    def test_attachment_add_is_detected_deletion_is_not(self) -> None:
        added = audit_diff({}, [("A", "WIP/e/scan.pdf", None)], self.config)
        self.assertIn("binary-extension.pdf", kinds(added))
        deleted = audit_diff({}, [("D", "WIP/e/scan.pdf", None)], self.config)
        self.assertNotIn("binary-extension.pdf", kinds(deleted))
        modified = audit_diff({}, [("M", "WIP/e/scan.pdf", None)], self.config)
        self.assertNotIn("binary-extension.pdf", kinds(modified))

    def test_attachment_inside_allowed_path_passes(self) -> None:
        config = GateConfig({"allow_paths": ["model/SOURCES/legal/"]})
        findings = audit_diff(
            {}, [("A", "model/SOURCES/legal/civil-code.pdf", None)], config
        )
        self.assertEqual(findings, [])

    def test_allow_strings_exempt_synthetic_tokens(self) -> None:
        config = GateConfig({"allow_strings": [FAKE_AWS_KEY]})
        findings = audit_diff(
            diff_for("tests/test_gate.py", [f'fake = "{FAKE_AWS_KEY}"']),
            [("A", "tests/test_gate.py", None)],
            config,
        )
        self.assertEqual(findings, [])

    def test_allow_strings_match_inside_wrapped_spans(self) -> None:
        config = GateConfig({"allow_strings": [FAKE_AWS_KEY]})
        line = f'conf api_key = "{FAKE_AWS_KEY}"'
        findings = audit_diff(
            diff_for("tests/test_gate.py", [line]),
            [("A", "tests/test_gate.py", None)],
            config,
        )
        self.assertEqual(findings, [])

    def test_disabled_detector_is_skipped(self) -> None:
        config = GateConfig({"disabled_detectors": ["pii"]})
        findings = audit_diff(
            diff_for("docs/x.md", [f"DNI {FAKE_DNI}"]),
            [("A", "docs/x.md", None)],
            config,
        )
        self.assertEqual([f for f in findings if f.detector == "pii"], [])

    def test_protected_path_covers_both_rename_sides(self) -> None:
        config = GateConfig({"protected_paths": ["WIP/evidence/**"]})
        renamed_out = audit_diff(
            {}, [("R", "docs/note.md", "WIP/evidence/note.md")], config
        )
        self.assertIn("protected-path-change", kinds(renamed_out))
        renamed_in = audit_diff(
            {}, [("R", "WIP/evidence/note.md", "docs/note.md")], config
        )
        self.assertIn("protected-path-change", kinds(renamed_in))

    def test_protected_path_blocks_even_if_allowed(self) -> None:
        config = GateConfig(
            {"allow_paths": ["WIP/"], "protected_paths": ["WIP/evidence/**"]}
        )
        findings = audit_diff({}, [("M", "WIP/evidence/x.md", None)], config)
        self.assertIn("protected-path-change", kinds(findings))

    def test_findings_redact_matched_values(self) -> None:
        findings = audit_diff(
            diff_for("src/main.py", [f'key = "{FAKE_AWS_KEY}"']),
            [("A", "src/main.py", None)],
            self.config,
        )
        for finding in findings:
            self.assertNotIn("IOSFODNN7EXAMPLE", finding.redacted)

    def test_config_schema_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            bad = Path(raw) / "push-gate.json"
            bad.write_text(json.dumps({"schema_version": "wrong"}))
            with self.assertRaises(ValueError):
                GateConfig.load(bad)

    def test_missing_config_file_is_empty_config(self) -> None:
        config = GateConfig.load(Path("/nonexistent/push-gate.json"))
        self.assertEqual(config.allow_paths, ())
        self.assertEqual(CONFIG_SCHEMA, "push-gate/config-v1")


HOOK = """#!/bin/sh
GATE="{gate}"
REPO_ROOT="$(git rev-parse --show-toplevel)"
status=0
while read -r local_ref local_sha remote_ref remote_sha; do
    case "$local_sha" in
        ''|*[!0]*) ;;
        *) continue ;;
    esac
    python3 "$GATE" --repo-root "$REPO_ROOT" \\
        --range "$remote_sha..$local_sha" || status=1
done
exit "$status"
"""


class CliTests(unittest.TestCase):
    GIT_ENV = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }

    def _repo(self, root: Path, hook: bool = False) -> Path:
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(root)],
            check=True,
            env={**os.environ, **self.GIT_ENV},
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", "base"],
            check=True,
            env={**os.environ, **self.GIT_ENV},
        )
        if hook:
            (root / ".githooks").mkdir()
            gate = SKILL_SCRIPTS / "pre_push_audit.py"
            (root / ".githooks" / "pre-push").write_text(
                HOOK.format(gate=gate)
            )
            (root / ".githooks" / "pre-push").chmod(0o755)
            subprocess.run(
                ["git", "-C", str(root), "config", "core.hooksPath", ".githooks"],
                check=True,
            )
        return root

    def _commit(self, root: Path, name: str, content: str) -> None:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        subprocess.run(
            ["git", "-C", str(root), "add", name], check=True
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "-m", name],
            check=True,
            env={**os.environ, **self.GIT_ENV},
        )

    def test_clean_commit_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self._repo(Path(raw))
            self._commit(root, "README.md", "hello\n")
            code = main(["--repo-root", str(root), "--range", "HEAD~1..HEAD"])
        self.assertEqual(code, 0)

    def test_secret_commit_exits_one(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self._repo(Path(raw))
            self._commit(root, "app.py", f'key = "{FAKE_AWS_KEY}"\n')
            code = main(["--repo-root", str(root), "--range", "HEAD~1..HEAD"])
        self.assertEqual(code, 1)

    def test_no_upstream_without_range_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self._repo(Path(raw))
            code = main(["--repo-root", str(root)])
        self.assertEqual(code, 2)

    def test_option_injection_range_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self._repo(Path(raw))
            self._commit(root, "README.md", "x\n")
            code = main(
                ["--repo-root", str(root), "--range=--output=/tmp/evil..HEAD"]
            )
        self.assertEqual(code, 2)
        self.assertFalse(Path("/tmp/evil").exists())

    def test_three_dot_range_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self._repo(Path(raw))
            code = main(
                ["--repo-root", str(root), "--range", "HEAD...HEAD"]
            )
        self.assertEqual(code, 2)

    def test_malformed_config_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self._repo(Path(raw))
            (root / "push-gate.json").write_text("{not json")
            code = main(["--repo-root", str(root), "--range", "HEAD~1..HEAD"])
        self.assertEqual(code, 2)

    def test_add_then_remove_inside_range_is_still_caught(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self._repo(Path(raw))
            self._commit(root, "secret.py", f'k = "{FAKE_AWS_KEY}"\n')
            subprocess.run(
                ["git", "-C", str(root), "rm", "-q", "secret.py"], check=True
            )
            subprocess.run(
                ["git", "-C", str(root), "commit", "-q", "-m", "remove"],
                check=True,
                env={**os.environ, **self.GIT_ENV},
            )
            code = main(["--repo-root", str(root), "--range", "HEAD~2..HEAD"])
        self.assertEqual(code, 1)

    def test_rename_destination_is_checked_via_cli(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self._repo(Path(raw))
            self._commit(root, "docs/note.md", "body\n")
            subprocess.run(
                ["git", "-C", str(root), "mv", "docs/note.md", "scan.pdf"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "commit", "-q", "-m", "rename"],
                check=True,
                env={**os.environ, **self.GIT_ENV},
            )
            code = main(["--repo-root", str(root), "--range", "HEAD~1..HEAD"])
        self.assertEqual(code, 1)

    def test_pathspec_magic_filename_is_scanned_literally(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self._repo(Path(raw))
            (root / ":(exclude)*").write_text(f'k = "{FAKE_AWS_KEY}"\n')
            subprocess.run(
                ["git", "-C", str(root), "add", "--", ":(literal):(exclude)*"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "commit", "-q", "-m", "magic"],
                check=True,
                env={**os.environ, **self.GIT_ENV},
            )
            code = main(["--repo-root", str(root), "--range", "HEAD~1..HEAD"])
        self.assertEqual(code, 1)

    def test_binary_noise_does_not_crash_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self._repo(Path(raw))
            blob = root / "noise.pdf"
            blob.write_bytes(b"\x00\xff\xfe" * 500)
            subprocess.run(["git", "-C", str(root), "add", "noise.pdf"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-q", "-m", "blob"],
                check=True,
                env={**os.environ, **self.GIT_ENV},
            )
            code = main(["--repo-root", str(root), "--range", "HEAD~1..HEAD"])
        self.assertEqual(code, 1)

    def test_non_utf8_filename_cannot_evade_scanning(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self._repo(Path(raw))
            env = {**os.environ, **self.GIT_ENV}
            weird = b"bad\xff_\xffsecret.py"
            hashed = subprocess.run(
                ["git", "-C", str(root), "hash-object", "-w", "--stdin"],
                input=f'k = "{FAKE_AWS_KEY}"\n',
                capture_output=True,
                text=True,
                check=True,
                env=env,
            ).stdout.strip()
            subprocess.run(
                ["git", "-C", str(root), "update-index", "--add",
                 "--cacheinfo", "100644", hashed, weird],
                check=True,
                env=env,
            )
            subprocess.run(
                ["git", "-C", str(root), "commit", "-q", "-m", "weird"],
                check=True,
                env=env,
            )
            code = main(["--repo-root", str(root), "--range", "HEAD~1..HEAD"])
        self.assertEqual(code, 1)

    def test_new_ref_push_audits_full_history(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self._repo(Path(raw), hook=True)
            self._commit(root, "README.md", "clean\n")
            subprocess.run(
                ["git", "-C", str(root), "checkout", "-q", "-b", "leak"],
                check=True,
            )
            self._commit(root, "secret.py", f'k = "{FAKE_AWS_KEY}"\n')
            subprocess.run(
                ["git", "-C", str(root), "rm", "-q", "secret.py"], check=True
            )
            subprocess.run(
                ["git", "-C", str(root), "commit", "-q", "-m", "remove-secret"],
                check=True,
                env={**os.environ, **self.GIT_ENV},
            )
            subprocess.run(
                ["git", "-C", str(root), "checkout", "-q", "main"],
                check=True,
            )
            remote = Path(raw) / "remote.git"
            subprocess.run(
                ["git", "init", "-q", "-b", "main", "--bare", str(remote)],
                check=True,
            )
            clean = subprocess.run(
                ["git", "-C", str(root), "push", "-q", str(remote), "main"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(clean.returncode, 0, clean.stderr)
            leak = subprocess.run(
                ["git", "-C", str(root), "push", "-q", str(remote), "leak"],
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(
            leak.returncode, 0, f"leak unexpectedly pushed: {leak.stderr}"
        )

    def test_sha256_repository_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(
                ["git", "init", "-q", "-b", "main",
                 "--object-format=sha256", str(root)],
                check=True,
            )
            env = {
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@example.com",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.com",
            }
            subprocess.run(
                ["git", "-C", str(root), "commit", "-q", "--allow-empty",
                 "-m", "base"],
                check=True,
                env=env,
            )
            (root / "app.py").write_text(f'k = "{FAKE_AWS_KEY}"\n')
            subprocess.run(["git", "-C", str(root), "add", "app.py"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-q", "-m", "oops"],
                check=True,
                env=env,
            )
            code = main(["--repo-root", str(root), "--range", "HEAD~1..HEAD"])
        self.assertEqual(code, 1)

    def test_hook_blocks_push_with_secret(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self._repo(Path(raw), hook=True)
            self._commit(root, "app.py", f'k = "{FAKE_AWS_KEY}"\n')
            remote = Path(raw) / "remote.git"
            subprocess.run(
                ["git", "init", "-q", "-b", "main", "--bare", str(remote)],
                check=True,
            )
            pushed = subprocess.run(
                ["git", "-C", str(root), "push", "-q", str(remote), "main"],
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(pushed.returncode, 0)
        self.assertIn("push-gate", pushed.stderr + pushed.stdout)

    def test_hook_allows_clean_push_and_new_branch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self._repo(Path(raw), hook=True)
            self._commit(root, "README.md", "clean\n")
            remote = Path(raw) / "remote.git"
            subprocess.run(
                ["git", "init", "-q", "-b", "main", "--bare", str(remote)],
                check=True,
            )
            first = subprocess.run(
                ["git", "-C", str(root), "push", "-q", str(remote), "main"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            subprocess.run(
                ["git", "-C", str(root), "checkout", "-q", "-b", "feature"],
                check=True,
            )
            self._commit(root, "docs.md", "also clean\n")
            second = subprocess.run(
                ["git", "-C", str(root), "push", "-q", str(remote), "feature"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(second.returncode, 0, second.stderr)


if __name__ == "__main__":
    unittest.main()

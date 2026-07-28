from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import assert_never

from tests import model_check_brain_compat_cases as cases


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "task18" / "legacy-compatibility-fixture.json"


def _load_fixture() -> dict[str, dict[str, str] | list[str] | str]:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    match raw:
        case {
            "schema_version": "task18-brain-compatibility-fixture/v1",
            "extra_common_files": dict(extra_common_files),
            "brain_file_overrides": dict(brain_file_overrides),
            "remove_paths": list(remove_paths),
            "wrong_model_templates": list(wrong_model_templates),
            "broken_template": str(broken_template),
        }:
            if not all(isinstance(key, str) and isinstance(value, str) for key, value in extra_common_files.items()):
                raise AssertionError("extra_common_files fixture entries must be strings")
            if not all(isinstance(key, str) and isinstance(value, str) for key, value in brain_file_overrides.items()):
                raise AssertionError("brain_file_overrides fixture entries must be strings")
            if not all(isinstance(value, str) for value in remove_paths):
                raise AssertionError("remove_paths fixture entries must be strings")
            if not all(isinstance(value, str) for value in wrong_model_templates):
                raise AssertionError("wrong_model_templates fixture entries must be strings")
            return {
                "extra_common_files": extra_common_files,
                "brain_file_overrides": brain_file_overrides,
                "remove_paths": remove_paths,
                "wrong_model_templates": wrong_model_templates,
                "broken_template": broken_template,
            }
        case unreachable:
            assert_never(unreachable)


def _replace_symlink(path: Path, target: Path) -> None:
    if path.is_symlink() or path.exists():
        path.unlink()
    path.symlink_to(target)


def _materialize_legacy_fixture(root: Path) -> tuple[Path, Path]:
    data = _load_fixture()
    common = cases.write_common(root)
    for rel, text in data["extra_common_files"].items():
        path = common / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    brain = root / "legacy-brain"
    brain.mkdir()
    reporter = cases.Reporter(root / "home-setup.log")
    cases.apply(brain, common, skip_full_reorder=True, switch_model=True, reporter=reporter)

    for rel, text in data["brain_file_overrides"].items():
        (brain / rel).write_text(text, encoding="utf-8")
    for rel in data["remove_paths"]:
        target = brain / rel
        if target.exists():
            target.unlink()

    old_model = root / "old-model"
    for rel in data["wrong_model_templates"]:
        common_rel = cases.MANAGED_TEMPLATES[rel]
        old_target = old_model / common_rel
        old_target.parent.mkdir(parents=True, exist_ok=True)
        old_target.write_text(f"# old {Path(common_rel).name}\n", encoding="utf-8")
        _replace_symlink(brain / rel, old_target)
    _replace_symlink(brain / data["broken_template"], root / "missing-template.common.md")
    return brain, common


def _count_codes(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        code = row["code"]
        if not isinstance(code, str):
            raise AssertionError("finding code must be a string")
        counts[code] = counts.get(code, 0) + 1
    return counts


class Task18BrainCompatibilityDiagnosticsTests(unittest.TestCase):
    def test_legacy_fixture_has_one_vault_three_wrong_model_and_guidance_only(self) -> None:
        # Given: an immutable task-18 recipe materialized into a temporary legacy brain.
        with tempfile.TemporaryDirectory() as raw:
            brain, common = _materialize_legacy_fixture(Path(raw))
            before = cases.manifest(brain)

            # When: read-only compatibility diagnostics are run through the task-local API.
            exit_code, payload = cases.compatibility_report(
                brain,
                common,
                ROOT / "model" / "OPERATING-MODEL.json",
                strict=True,
            )
            findings = payload["findings"]
            after = cases.manifest(brain)

        # Then: diagnostics are deterministic, guidance-only, and the brain is unchanged.
        self.assertEqual(before, after)
        self.assertEqual(exit_code, 1)
        self.assertIsInstance(findings, list)
        counts = _count_codes(findings)
        self.assertEqual(counts["brain-wrapper-legacy-vault"], 1)
        self.assertEqual(counts["brain-template-wrong-model"], 3)
        self.assertEqual(counts["brain-template-broken"], 1)
        self.assertIn("brain-wrapper-missing", counts)
        self.assertIn("brain-wrapper-customized", counts)
        absolute_rows = [
            row
            for row in findings
            if row["path"] == "AGENTS.md" and row["code"] == "brain-wrapper-wrong-target"
        ]
        self.assertEqual(len(absolute_rows), 1)
        self.assertIn("absolute", str(absolute_rows[0]["message"]))
        for row in findings:
            self.assertEqual(set(row), {"code", "family", "severity", "path", "target", "message"})

    def test_task_local_cli_has_no_repair_or_apply_surface(self) -> None:
        # Given: the task-local diagnostic CLI is inspected directly.
        # When: help text is rendered without scanning a brain.
        result = subprocess.run(
            ["python3", str(ROOT / "model" / "SCRIPTS" / "model_check_brain_compat.py"), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        # Then: no mutation-oriented command surface is exposed.
        self.assertEqual(result.returncode, 0)
        output = result.stdout
        self.assertNotIn("--repair", output)
        self.assertNotIn("--apply", output)
        self.assertNotIn("setup", output.lower())


if __name__ == "__main__":
    unittest.main()

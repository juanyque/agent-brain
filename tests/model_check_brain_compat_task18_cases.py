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
CLI = ROOT / "model" / "SCRIPTS" / "model_check.py"


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


def materialize_legacy_fixture(root: Path) -> tuple[Path, Path]:
    data = _load_fixture()
    common = cases.write_common(root)
    for rel, text in data["extra_common_files"].items():
        path = common / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    brain = root / "legacy-brain"
    brain.mkdir()
    cases.apply(brain, common, skip_full_reorder=True, switch_model=True, reporter=cases.Reporter(root / "home-setup.log"))
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


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class Task18IntegratedBrainCompatibilityTests(unittest.TestCase):
    def test_legacy_fixture_has_one_vault_and_three_wrong_model_findings(self) -> None:
        # Given: a temporary legacy brain generated from the immutable task18 fixture.
        with tempfile.TemporaryDirectory() as raw:
            brain, common = materialize_legacy_fixture(Path(raw))
            before = cases.manifest(brain)

            # When: diagnostics are run through canonical model_check.py routing.
            result = _run_cli(
                "--root",
                str(common.parent),
                "--model",
                str(ROOT / "model" / "OPERATING-MODEL.json"),
                "--brain",
                str(brain),
                "--only",
                "brain-compatibility",
                "--strict",
                "--format",
                "json",
            )
            payload = json.loads(result.stdout)
            after = cases.manifest(brain)

        # Then: exact task18 counts are present and the scanned brain was not changed.
        codes = [row["code"] for row in payload["findings"]]
        self.assertEqual(result.returncode, 1)
        self.assertEqual(before, after)
        self.assertEqual(codes.count("brain-wrapper-legacy-vault"), 1)
        self.assertEqual(codes.count("brain-template-wrong-model"), 3)
        self.assertIn("brain-template-broken", codes)
        self.assertIn("brain-wrapper-missing", codes)
        self.assertIn("brain-wrapper-customized", codes)
        self.assertEqual(
            1,
            sum(1 for row in payload["findings"] if row["path"] == "AGENTS.md" and row["code"] == "brain-wrapper-wrong-target"),
        )

    def test_source_report_exposes_canonical_brain_compatibility_support_module(self) -> None:
        # Given: canonical source reporting is the public report surface for checker source files.
        # When: the source digest report is rendered.
        result = _run_cli("--source-digest", "--format", "json")
        payload = json.loads(result.stdout)

        # Then: the final support module has a canonical path, not a task-lane name.
        paths = {row["path"] for row in payload["files"]}
        self.assertIn("model/SCRIPTS/model_check_brain_compat_paths.py", paths)
        self.assertNotIn("model/SCRIPTS/model_check_brain_compat_task18.py", paths)

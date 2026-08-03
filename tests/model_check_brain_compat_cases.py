from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "model" / "SCRIPTS"
if str(SCRIPTS) in sys.path:
    sys.path.remove(str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS))
loaded_common = sys.modules.get("_common")
if loaded_common is not None:
    loaded_path = getattr(loaded_common, "__file__", "")
    if loaded_path and Path(loaded_path).resolve().parent != SCRIPTS:
        del sys.modules["_common"]

from _common import Reporter  # noqa: E402
from home_setup import apply  # noqa: E402
from model_check_brain_compat import (  # noqa: E402
    compatibility_report,
    run,
    scan_brain_compatibility,
)


MANAGED_TEMPLATES = {
    "TEMPLATES/WIP Template.md": "TEMPLATES/TEMPLATE.wip.common.md",
    "TEMPLATES/WIP Session Template.md": "TEMPLATES/TEMPLATE.wip-session.common.md",
    "TEMPLATES/Daily Note Template.md": "TEMPLATES/TEMPLATE.daily-note.common.md",
    "TEMPLATES/Issue Template.md": "TEMPLATES/TEMPLATE.issue.common.md",
}


def write_common(root: Path) -> Path:
    common = root / "model"
    common.mkdir()
    common_files = {
        "AGENTS.common.md": "# Agent Policy\n\n## Core operating assumptions\n",
        "BRAIN.common.md": "# Brain\n\n## Concepts\n",
        "JOBS.common.md": "# Jobs\n\n## Schedule\n",
        "RULES-DAILY-NOTES.common.md": "# Daily\n\n## Daily policy\n",
        "RULES-FILE-NAMING.common.md": "# Files\n\n## File policy\n",
        "RULES-LINKS.common.md": "# Links\n\n## Link policy\n",
        "TASK_TYPES/example.common.md": "# Example\n\n## Example policy\n",
        "TEMPLATES/TEMPLATE.evidence-note.common.md": "# Evidence\n",
    }
    for rel, text in common_files.items():
        path = common / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for rel in MANAGED_TEMPLATES.values():
        path = common / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.name}\n", encoding="utf-8")
    return common


def wrapper(common_rel: str, section: str | None = None) -> str:
    extra = f"\n## Adds to \"{section}\"\n\n- local note\n" if section else ""
    return f"# Local\n\nThis wrapper follows `_COMMON/{common_rel}`.\n{extra}"


def manifest(root: Path) -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    for parent, dirs, files in os.walk(root, followlinks=False):
        current = Path(parent)
        names = sorted([*dirs, *files])
        for name in names:
            path = current / name
            rel = path.relative_to(root).as_posix()
            mode = os.lstat(path).st_mode
            if stat.S_ISLNK(mode):
                entries.append((rel, "symlink", os.readlink(path)))
            elif stat.S_ISREG(mode):
                entries.append((rel, "file", path.read_bytes().hex()))
            elif stat.S_ISDIR(mode):
                entries.append((rel, "dir", ""))
        dirs[:] = [name for name in sorted(dirs) if not (current / name).is_symlink()]
    return entries


class BrainCompatibilityCaseTests(unittest.TestCase):
    def test_classifies_wrappers_templates_and_escapes_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            common = write_common(root)
            brain = root / "brain"
            brain.mkdir()
            (brain / "_COMMON").symlink_to(common)
            (brain / "BRAIN.md").write_text(wrapper("VAULT.md"), encoding="utf-8")
            (brain / "JOBS.md").write_text(wrapper("JOBS.common.md", "missing"), encoding="utf-8")
            (brain / "RULES-FILE-NAMING.md").write_text(
                wrapper("RULES-LINKS.common.md"),
                encoding="utf-8",
            )
            (brain / "RULES-LINKS.md").write_text(
                wrapper("RULES-LINKS.common.md", "link   policy"),
                encoding="utf-8",
            )
            (brain / "RULES-DAILY-NOTES.md").symlink_to(root / "gone.md")
            outside = root / "outside"
            outside.mkdir()
            (brain / "TASK_TYPES").symlink_to(outside, target_is_directory=True)
            templates = brain / "TEMPLATES"
            templates.mkdir()
            (templates / "WIP Template.md").symlink_to(root / "missing-template.md")
            old = root / "old-model"
            (old / "TEMPLATES").mkdir(parents=True)
            old_wip = old / "TEMPLATES/TEMPLATE.wip-session.common.md"
            old_wip.write_text("# old\n", encoding="utf-8")
            (templates / "WIP Session Template.md").symlink_to(old_wip)
            (templates / "Daily Note Template.md").symlink_to(
                "../_COMMON/TEMPLATES/TEMPLATE.daily-note.common.md",
            )
            (templates / "Issue Template.md").symlink_to(
                "../_COMMON/TEMPLATES/TEMPLATE.issue.common.md",
            )
            before = manifest(brain)

            findings = scan_brain_compatibility(brain, common, ROOT / "model/OPERATING-MODEL.json")
            counts: dict[str, int] = {}
            for finding in findings:
                counts[finding.code] = counts.get(finding.code, 0) + 1
            after = manifest(brain)

        self.assertEqual(after, before)
        self.assertEqual(
            counts,
            {
                "brain-conditional-template-absent": 1,
                "brain-managed-entry-dangling": 1,
                "brain-managed-path-escape": 1,
                "brain-template-broken": 1,
                "brain-template-wrong-model": 1,
                "brain-unmanaged-external-symlink": 1,
                "brain-wrapper-customized": 1,
                "brain-wrapper-legacy-vault": 1,
                "brain-wrapper-missing": 1,
                "brain-wrapper-missing-common-section": 1,
                "brain-wrapper-wrong-target": 1,
            },
        )
        self.assertEqual(
            {"error": 7, "info": 2, "warning": 2},
            {level: sum(1 for item in findings if item.severity == level) for level in ("error", "info", "warning")},
        )

    def test_fresh_generated_brain_has_no_strict_failures(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            common = write_common(root)
            brain = root / "brain"
            brain.mkdir()
            reporter = Reporter(root / "home-setup.log")
            apply(brain, common, skip_full_reorder=True, switch_model=True, reporter=reporter)
            before = manifest(brain)

            exit_code, payload = compatibility_report(
                brain,
                common,
                ROOT / "model/OPERATING-MODEL.json",
                strict=True,
            )
            findings = payload["findings"]
            after = manifest(brain)

        self.assertEqual(after, before)
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            {"brain-conditional-template-absent"},
            {row["code"] for row in findings},
        )
        self.assertEqual({"info"}, {row["severity"] for row in findings})

    def test_cli_strict_preserves_declared_severities_and_only_errors_exit_one(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            common = write_common(root)
            warning_brain = root / "warning"
            warning_brain.mkdir()
            reporter = Reporter(root / "warning.log")
            apply(warning_brain, common, skip_full_reorder=True, switch_model=True, reporter=reporter)
            (warning_brain / "BRAIN.md").write_text(wrapper("VAULT.md"), encoding="utf-8")
            error_brain = root / "error"
            error_brain.mkdir()
            reporter = Reporter(root / "error.log")
            apply(error_brain, common, skip_full_reorder=True, switch_model=True, reporter=reporter)
            (error_brain / "AGENTS.md").unlink()

            non_strict_code, non_strict_out = run(
                [
                    "--brain",
                    str(warning_brain),
                    "--common",
                    str(common),
                    "--model",
                    str(ROOT / "model/OPERATING-MODEL.json"),
                    "--format",
                    "json",
                ],
            )
            strict_code, strict_out = run(
                [
                    "--brain",
                    str(warning_brain),
                    "--common",
                    str(common),
                    "--model",
                    str(ROOT / "model/OPERATING-MODEL.json"),
                    "--strict",
                    "--format",
                    "json",
                ],
            )
            error_code, error_out = run(
                [
                    "--brain",
                    str(error_brain),
                    "--common",
                    str(common),
                    "--model",
                    str(ROOT / "model/OPERATING-MODEL.json"),
                    "--strict",
                    "--format",
                    "json",
                ],
            )

        self.assertEqual(non_strict_code, 0)
        self.assertEqual(strict_code, 0)
        self.assertEqual(error_code, 1)
        self.assertEqual(json.loads(non_strict_out)["findings"], json.loads(strict_out)["findings"])
        self.assertIn("brain-wrapper-missing", {row["code"] for row in json.loads(error_out)["findings"]})


if __name__ == "__main__":
    unittest.main()

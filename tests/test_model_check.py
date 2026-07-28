from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import fields, replace
from pathlib import Path

from tests import model_check_brain_compat_cases as brain_compat_cases
from tests import model_check_brain_compat_task18_cases as brain_compat_task18_cases
from tests import model_check_ownership_cases as ownership_cases
from tests import model_check_route_contract_cases as route_contract_cases
from tests import test_session_open as session_open_tests
from tests.model_check_stale_cases import write_model


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "model" / "SCRIPTS" / "model_check.py"
MODEL = ROOT / "model" / "OPERATING-MODEL.json"
SESSION_OPEN = ROOT / "skills" / "brain" / "scripts" / "session_open.py"
BASELINE = ROOT / "tests" / "fixtures" / "model-context-baseline.json"
BASELINE_DIGEST = ROOT / "tests" / "fixtures" / "model-context-baseline.sha256"
STALE_SKILL_PATTERN = "SKILLS/" + "obsidian"
STALE_TEMPLATE_PATTERN = "TEMPLATE.daily" + "-note.md"


def run_cli(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(CLI), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def parsed_json(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    return json.loads(result.stdout)


def decoded_normal_text(raw: str) -> dict[str, object]:
    lines = raw.splitlines()
    source_kind, source_digest = lines[0].split("\t", 1)
    if source_kind != "source_digest":
        raise AssertionError(f"unexpected text source row: {lines[0]}")
    findings: list[dict[str, object]] = []
    for line in lines[1:]:
        severity, family, code, path, target, message = line.split("\t", 5)
        findings.append(
            {
                "code": code,
                "family": family,
                "message": message,
                "path": path,
                "severity": severity,
                "target": target,
            }
        )
    return {"findings": findings, "source_digest": source_digest}


def decoded_manifest_text(raw: str) -> dict[str, object]:
    manifest: dict[str, object] = {}
    common: dict[str, object] = {}
    for line in raw.splitlines():
        key, value = line.split("\t", 1)
        match key:
            case "brain" | "state":
                manifest[key] = value
            case "common.desired" | "common.path" | "common.status":
                common[key.removeprefix("common.")] = value
            case unreachable:
                raise AssertionError(f"unexpected manifest text row: {unreachable}")
    manifest["common"] = common
    return manifest


def fixture_brain(root: Path, common: Path, state: str) -> Path:
    brain = root / state
    brain.mkdir()
    match state:
        case "fresh":
            (brain / "_COMMON").symlink_to(common)
        case "missing":
            (brain / "AGENTS.md").write_text("# local\n", encoding="utf-8")
        case "wrong":
            wrong = root / "wrong-model"
            wrong.mkdir(exist_ok=True)
            (brain / "_COMMON").symlink_to(wrong)
        case "broken":
            (brain / "_COMMON").symlink_to(root / "missing-model")
        case "file":
            (brain / "_COMMON").write_text("not a symlink\n", encoding="utf-8")
        case unreachable:
            raise AssertionError(f"unknown fixture state: {unreachable}")
    return brain


def snapshot_tree(root: Path) -> list[tuple[str, str, bytes]]:
    entries: list[tuple[str, str, bytes]] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((rel, "symlink", os.readlink(path).encode()))
        elif path.is_file():
            entries.append((rel, "file", path.read_bytes()))
        elif path.is_dir():
            entries.append((rel, "dir", b""))
    return entries


def load_session_open() -> object:
    spec = importlib.util.spec_from_file_location("session_open_for_tests", SESSION_OPEN)
    if spec is None or spec.loader is None:
        raise AssertionError("session_open.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_normal_stale_model(path: Path) -> None:
    write_model(path)
    stale_fixture = json.loads(path.read_text(encoding="utf-8"))
    normal_contract = json.loads(MODEL.read_text(encoding="utf-8"))["finding_contract"]
    path.write_text(
        json.dumps(
            {
                "finding_contract": normal_contract,
                "stale_reference_contract": stale_fixture["stale_reference_contract"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def run_case_method(case_class: type[unittest.TestCase], method_name: str) -> None:
    getattr(case_class(method_name), method_name)()


def _task_type_wrapper_common_entries_are_loaded_once(self: unittest.TestCase) -> None:
    from session_open import extract_task_types

    with tempfile.TemporaryDirectory() as raw:
        task_index = Path(raw) / "TASK_TYPES.md"
        task_index.write_text(
            "- [[basename-collision-cleanup]] Resolve duplicate basenames\n"
            "- [[dead-code-detection]] Find unused code\n"
            "- [[basename-collision-cleanup]] Resolve duplicate basenames\n",
            encoding="utf-8",
        )

        task_types = extract_task_types(task_index)

    self.assertEqual(
        task_types,
        [
            "- [[basename-collision-cleanup]] Resolve duplicate basenames",
            "- [[dead-code-detection]] Find unused code",
        ],
    )


setattr(
    session_open_tests.SessionRecoveryTests,
    "test_task_type_wrapper_common_entries_are_loaded_once",
    _task_type_wrapper_common_entries_are_loaded_once,
)


class ModelCheckCliTests(unittest.TestCase):
    def test_normal_defaults_exclude_brain_and_committed_families(self) -> None:
        result = run_cli("--format", "json")
        body = parsed_json(result)
        families = {finding["family"] for finding in body["findings"]}

        self.assertEqual(result.returncode, 0)
        self.assertIn("source_digest", body)
        self.assertNotIn("brain-compatibility", families)
        self.assertNotIn("committed-scope", families)

    def test_brain_without_only_adds_brain_families(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = fixture_brain(Path(raw), ROOT / "model", "missing")
            result = run_cli("--brain", str(brain), "--format", "json")
            body = parsed_json(result)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            {finding["family"] for finding in body["findings"]},
            {"brain-compatibility"},
        )
        self.assertIn(
            "brain-wrapper-missing",
            {finding["code"] for finding in body["findings"]},
        )

    def test_only_selects_exact_expansion(self) -> None:
        result = run_cli("--only", "worktree-scope", "--format", "json")
        body = parsed_json(result)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(body["findings"], [])

    def test_brain_with_only_nonbrain_adds_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = fixture_brain(Path(raw), ROOT / "model", "missing")
            result = run_cli(
                "--brain",
                str(brain),
                "--only",
                "worktree-scope",
                "--format",
                "json",
            )
            body = parsed_json(result)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(body["findings"], [])

    def test_brain_selector_requires_brain(self) -> None:
        result = run_cli("--only", "brain-compatibility", "--format", "json")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("--brain", result.stderr)

    def test_committed_selector_requires_git_base(self) -> None:
        result = run_cli("--only", "committed-scope", "--format", "json")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("--git-base", result.stderr)

    def test_git_base_without_committed_selector_exits_two(self) -> None:
        result = run_cli("--git-base", "HEAD", "--format", "json")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("committed", result.stderr)

    def test_nonstrict_error_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = fixture_brain(Path(raw), ROOT / "model", "wrong")
            result = run_cli(
                "--brain",
                str(brain),
                "--only",
                "brain-compatibility",
                "--format",
                "json",
            )
            body = parsed_json(result)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(body["findings"][0]["severity"], "error")

    def test_strict_errors_exit_one_but_warnings_exit_zero(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            common = brain_compat_cases.write_common(root)
            warning_brain = root / "warning"
            warning_brain.mkdir()
            warning_reporter = brain_compat_cases.Reporter(root / "warning.log")
            brain_compat_cases.apply(
                warning_brain,
                common,
                skip_full_reorder=True,
                switch_model=True,
                reporter=warning_reporter,
            )
            (warning_brain / "BRAIN.md").write_text(
                brain_compat_cases.wrapper("VAULT.md"),
                encoding="utf-8",
            )
            error_brain = fixture_brain(root, ROOT / "model", "file")

            warning = run_cli(
                "--root",
                str(root),
                "--model",
                str(MODEL),
                "--strict",
                "--brain",
                str(warning_brain),
                "--only",
                "brain-compatibility",
                "--format",
                "json",
            )
            error = run_cli(
                "--strict",
                "--brain",
                str(error_brain),
                "--only",
                "brain-compatibility",
                "--format",
                "json",
            )

        self.assertEqual(warning.returncode, 0)
        self.assertEqual(error.returncode, 1)

    def test_manifest_only_requires_brain_and_rejects_incompatible_modes(self) -> None:
        missing_brain = run_cli("--manifest-only", "--format", "json")
        with tempfile.TemporaryDirectory() as raw:
            brain = fixture_brain(Path(raw), ROOT / "model", "fresh")
            ok = run_cli("--manifest-only", "--brain", str(brain), "--format", "json")
            rejected = run_cli(
                "--manifest-only",
                "--brain",
                str(brain),
                "--strict",
                "--format",
                "json",
            )
            body = parsed_json(ok)

        self.assertEqual(missing_brain.returncode, 2)
        self.assertEqual(ok.returncode, 0)
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(body["common"]["status"], "ok")
        self.assertEqual(body["state"], "maintenance")

    def test_source_digest_and_context_report_reject_incompatible_modes(self) -> None:
        source = run_cli("--source-digest", "--format", "json")
        context = run_cli("--context-report", "--format", "json")
        rejected = run_cli("--source-digest", "--strict", "--format", "json")
        both = run_cli("--source-digest", "--context-report", "--format", "json")

        self.assertEqual(source.returncode, 0)
        self.assertIn("files", parsed_json(source))
        self.assertEqual(context.returncode, 0)
        self.assertIn("scenarios", parsed_json(context))
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(both.returncode, 2)

    def test_format_text_and_json_change_representation_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = fixture_brain(Path(raw), ROOT / "model", "wrong")
            json_result = run_cli(
                "--brain",
                str(brain),
                "--only",
                "brain-compatibility",
                "--format",
                "json",
            )
            text_result = run_cli(
                "--brain",
                str(brain),
                "--only",
                "brain-compatibility",
                "--format",
                "text",
            )

        self.assertEqual(json_result.returncode, text_result.returncode)
        self.assertEqual(decoded_normal_text(text_result.stdout), parsed_json(json_result))

    def test_manifest_text_and_json_change_representation_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = fixture_brain(Path(raw), ROOT / "model", "fresh")
            json_result = run_cli(
                "--manifest-only",
                "--brain",
                str(brain),
                "--format",
                "json",
            )
            text_result = run_cli(
                "--manifest-only",
                "--brain",
                str(brain),
                "--format",
                "text",
            )

        self.assertEqual(json_result.returncode, text_result.returncode)
        self.assertEqual(decoded_manifest_text(text_result.stdout), parsed_json(json_result))

    def test_findings_sort_by_stable_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = fixture_brain(root, ROOT / "model", "file")
            result = run_cli(
                "--brain",
                str(brain),
                "--only",
                "brain-compatibility,worktree-scope",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        keys = [
            (
                {"error": 0, "warning": 1, "info": 2}[finding["severity"]],
                finding["code"],
                finding["path"].encode(),
                finding["target"].encode(),
                finding["message"],
            )
            for finding in findings
        ]
        self.assertEqual(keys, sorted(keys))

    def test_malformed_metadata_is_schema_error_stderr_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model = root / "bad.json"
            model.write_text('{"finding_contract":{"families":[]}}\n', encoding="utf-8")
            result = run_cli("--model", str(model), "--format", "json")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("metadata", result.stderr)

    def test_unexpected_internal_failure_exits_three_with_no_partial_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = run_cli("--model", raw, "--format", "json")

        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, "")
        self.assertIn("internal", result.stderr)

    def test_source_digest_changes_when_source_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            clone = Path(raw) / "clone"
            shutil.copytree(ROOT, clone, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            before = parsed_json(run_cli("--source-digest", "--root", str(clone), "--format", "json"))
            target = clone / "model" / "AGENTS.common.md"
            target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            after = parsed_json(run_cli("--source-digest", "--root", str(clone), "--format", "json"))

        self.assertNotEqual(before["source_digest"], after["source_digest"])

    def test_wrong_broken_and_non_symlink_common_states_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            states = ("wrong", "broken", "file")
            codes: list[set[str]] = []
            for state in states:
                brain = fixture_brain(root, ROOT / "model", state)
                result = run_cli(
                    "--brain",
                    str(brain),
                    "--only",
                    "brain-compatibility",
                    "--format",
                    "json",
                )
                codes.append({finding["code"] for finding in parsed_json(result)["findings"]})

        self.assertIn("common-link-wrong-target", codes[0])
        self.assertIn("common-link-broken", codes[1])
        self.assertIn("common-link-not-symlink", codes[2])

    def test_source_and_fixture_brain_are_not_mutated(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = fixture_brain(root, ROOT / "model", "broken")
            brain_before = snapshot_tree(brain)
            model_before = hashlib.sha256(MODEL.read_bytes()).hexdigest()

            result = run_cli(
                "--brain",
                str(brain),
                "--only",
                "brain-compatibility",
                "--format",
                "json",
            )

            brain_after = snapshot_tree(brain)
            model_after = hashlib.sha256(MODEL.read_bytes()).hexdigest()

        self.assertEqual(result.returncode, 0)
        self.assertEqual(brain_before, brain_after)
        self.assertEqual(model_before, model_after)


class BrainCompatibilityTests(
    brain_compat_cases.BrainCompatibilityCaseTests,
    brain_compat_task18_cases.Task18IntegratedBrainCompatibilityTests,
):
    pass


class StaleReferenceTests(unittest.TestCase):
    def test_only_selects_stale_families_and_codes_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model = root / "model" / "OPERATING-MODEL.json"
            write_normal_stale_model(model)
            (root / "doc.md").write_text(
                "\n".join(
                    [
                        f"Use {STALE_SKILL_PATTERN} for tools.",
                        f"Daily shape is {STALE_TEMPLATE_PATTERN}.",
                        "Archive to ARCHIVED/Reports/report.md.",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(model),
                "--only",
                "stale-reference,missing-target,review-archive-destination",
                "--format",
                "json",
            )
            rows = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            [row["code"] for row in rows],
            [
                "missing-target",
                "review-archive-destination",
                "stale-architecture-reference",
            ],
        )
        self.assertEqual(
            {row["family"] for row in rows},
            {"review-archive", "stale-reference", "target-existence"},
        )
        self.assertEqual({tuple(row) for row in rows}, {(
            "code",
            "family",
            "message",
            "path",
            "severity",
            "target",
        )})

    def test_strict_stale_errors_exit_one_and_do_not_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model = root / "model" / "OPERATING-MODEL.json"
            write_normal_stale_model(model)
            doc = root / "doc.md"
            doc.write_text("ARCHIVED/Reports/report.md\n", encoding="utf-8")
            before = snapshot_tree(root)

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(model),
                "--strict",
                "--only",
                "review-archive",
                "--format",
                "json",
            )
            after = snapshot_tree(root)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        self.assertEqual(before, after)
        self.assertEqual(
            parsed_json(result)["findings"][0]["code"],
            "review-archive-destination",
        )

    def test_stale_text_and_json_change_representation_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model = root / "model" / "OPERATING-MODEL.json"
            write_normal_stale_model(model)
            (root / "doc.md").write_text(
                f"Use {STALE_SKILL_PATTERN} and {STALE_TEMPLATE_PATTERN}.\n",
                encoding="utf-8",
            )

            json_result = run_cli(
                "--root",
                str(root),
                "--model",
                str(model),
                "--strict",
                "--only",
                "stale-reference,target-existence",
                "--format",
                "json",
            )
            text_result = run_cli(
                "--root",
                str(root),
                "--model",
                str(model),
                "--strict",
                "--only",
                "stale-reference,target-existence",
                "--format",
                "text",
            )

        self.assertEqual(json_result.returncode, 1)
        self.assertEqual(json_result.returncode, text_result.returncode)
        self.assertEqual(len(text_result.stdout.splitlines()[1].split("\t")), 6)
        self.assertEqual(decoded_normal_text(text_result.stdout), parsed_json(json_result))


class OwnershipContractTests(route_contract_cases.RouteContractCases, unittest.TestCase):

    def test_all_routes_resolve(self) -> None:
        run_case_method(
            ownership_cases.OwnershipContractCases,
            "test_all_declared_routes_have_parseable_common_rows_and_resolve_targets",
        )

    def test_missing_route_target_is_rejected(self) -> None:
        run_case_method(
            ownership_cases.OwnershipContractCases,
            "test_missing_route_target_is_rejected_with_contract_code",
        )

    def test_git_authority_is_explicit(self) -> None:
        run_case_method(
            ownership_cases.OwnershipContractCases,
            "test_common_git_authority_requires_explicit_git_authorization",
        )

    def test_git_authority_parser_regression_is_discovered(self) -> None:
        run_case_method(
            ownership_cases.OwnershipContractCases,
            "test_git_authority_parser_accepts_injected_malformed_policy_text",
        )

    def test_attachment_rule_is_routed(self) -> None:
        run_case_method(
            ownership_cases.OwnershipContractCases,
            "test_attachment_rule_is_canonical_destination",
        )

    def test_missing_attachment_destination_is_rejected(self) -> None:
        run_case_method(
            ownership_cases.OwnershipContractCases,
            "test_missing_attachment_destination_is_rejected_as_unmapped_cluster",
        )

    def test_missing_skills_audience_is_rejected(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "model.json"
            model["audience_contract"] = [
                row
                for row in model["audience_contract"]
                if row["path"] != "skills/brain/SKILL.md"
            ]
            path.write_text(
                json.dumps(model, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            result = run_cli(
                "--model",
                str(path),
                "--strict",
                "--only",
                "uncovered-audience",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual(findings[0]["code"], "uncovered-audience")
        self.assertEqual(findings[0]["path"], "skills/brain/SKILL.md")

    def test_root_agents_is_absent_from_brain_context(self) -> None:
        report = parsed_json(run_cli("--context-report", "--format", "json"))
        paths = {
            segment["path"]
            for scenario in report["scenarios"]
            for segment in scenario["segments"]
        }
        disk_reads = {
            read
            for scenario in report["scenarios"]
            for read in scenario["disk_reads"]
        }

        self.assertNotIn("AGENTS.md", paths)
        self.assertNotIn("AGENTS.md", disk_reads)
        self.assertNotIn(
            "AGENTS.md",
            json.loads(MODEL.read_text(encoding="utf-8"))["context_contract"][
                "conditional_artifacts"
            ],
        )

    def test_brain_contains_only_conceptual_clusters(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        brain_owners = [
            row
            for row in model["policy_owners"]
            if row["owner"] == "model/BRAIN.common.md"
        ]
        result = run_cli(
            "--strict",
            "--only",
            "misplaced-policy-owner,duplicate-policy-owner",
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(parsed_json(result)["findings"], [])
        self.assertEqual(
            [(row["policy_id"], row["kind"]) for row in brain_owners],
            [("policy.information-architecture", "conceptual")],
        )

    def test_operational_policy_id_owned_by_brain_is_rejected(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        mutated = dict(
            next(
                row
                for row in model["policy_owners"]
                if row["policy_id"] == "policy.attachments"
            ),
        )
        mutated["owner"] = "model/BRAIN.common.md"
        model["policy_owners"] = [
            mutated if row["policy_id"] == "policy.attachments" else row
            for row in model["policy_owners"]
        ]
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "model.json"
            path.write_text(
                json.dumps(model, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            result = run_cli(
                "--model",
                str(path),
                "--strict",
                "--only",
                "misplaced-policy-owner",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            {finding["code"] for finding in findings},
            {"misplaced-policy-owner"},
        )
        self.assertEqual(
            {finding["path"] for finding in findings},
            {"model/BRAIN.common.md"},
        )

    def test_operational_brain_prose_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shutil.copytree(ROOT / "model", root / "model", ignore=shutil.ignore_patterns("__pycache__"))
            brain = root / "model" / "BRAIN.common.md"
            brain.write_text(
                brain.read_text(encoding="utf-8")
                + "\n- Agents must preserve traceability and avoid destructive cleanup.\n",
                encoding="utf-8",
            )
            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "misplaced-policy-owner",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            {finding["code"] for finding in findings},
            {"misplaced-policy-owner"},
        )
        self.assertEqual(
            {finding["path"] for finding in findings},
            {"model/BRAIN.common.md"},
        )


class SessionOwnershipTests(unittest.TestCase):
    def test_repository_documents_satisfy_canonical_session_contract(self) -> None:
        result = run_cli(
            "--strict",
            "--only",
            "session-ownership",
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(parsed_json(result)["findings"], [])

    def test_duplicate_session_policy_id_is_rejected(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        model["policy_owners"].append(
            {
                "kind": "operational",
                "owner": "model/JOBS.common.md",
                "policy_id": "policy.session-lifecycle",
            }
        )
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "model.json"
            path.write_text(
                json.dumps(model, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            result = run_cli(
                "--model",
                str(path),
                "--strict",
                "--only",
                "duplicate-policy-owner",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            {finding["code"] for finding in parsed_json(result)["findings"]},
            {"duplicate-policy-owner"},
        )

    def test_session_open_is_unique_authority(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shutil.copytree(ROOT / "model", root / "model", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(ROOT / "skills", root / "skills", ignore=shutil.ignore_patterns("__pycache__"))
            session_rules = root / "model" / "RULES-SESSION-LIFECYCLE.common.md"
            session_rules.write_text(
                session_rules.read_text(encoding="utf-8").replace(
                    "| canonical-open-authority | session_open.py | unique |",
                    "| canonical-open-authority | session_bootstrap.py | unique |",
                ),
                encoding="utf-8",
            )

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "stale-open-authority",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(parsed_json(result)["findings"][0]["code"], "stale-open-authority")

    def test_jobs_flow_checklist_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shutil.copytree(ROOT / "model", root / "model", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(ROOT / "skills", root / "skills", ignore=shutil.ignore_patterns("__pycache__"))
            jobs = root / "model" / "JOBS.common.md"
            jobs.write_text(
                jobs.read_text(encoding="utf-8")
                + "\n### Tasks\n- Run the Flow 1 checklist.\n",
                encoding="utf-8",
            )

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "jobs-flow-checklist",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(parsed_json(result)["findings"][0]["code"], "jobs-flow-checklist")

    def test_git_command_bearing_model_docs_require_user_authorization(self) -> None:
        result = run_cli(
            "--strict",
            "--only",
            "git-authority-explicit",
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(parsed_json(result)["findings"], [])

    def test_unconditional_git_operation_in_lifecycle_doc_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shutil.copytree(ROOT / "model", root / "model", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(ROOT / "skills", root / "skills", ignore=shutil.ignore_patterns("__pycache__"))
            lifecycle = root / "model" / "RULES-SESSION-LIFECYCLE.common.md"
            lifecycle.write_text(
                lifecycle.read_text(encoding="utf-8")
                + "\n## Test-only Git operation fixture\n\n"
                + "When stale work is found, run `git mv WIP/example MEMORY/example` "
                + "as part of cleanup.\n",
                encoding="utf-8",
            )

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "git-authority-explicit",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual([finding["code"] for finding in findings], ["git-authority-explicit"])
        self.assertEqual(findings[0]["path"], "model/RULES-SESSION-LIFECYCLE.common.md")
        self.assertIn("line:", findings[0]["target"])


class EvidenceOwnershipTests(unittest.TestCase):
    def test_repository_documents_satisfy_canonical_evidence_contract(self) -> None:
        result = run_cli(
            "--strict",
            "--only",
            "evidence-ownership,review-archive,review-status",
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(parsed_json(result)["findings"], [])

    def test_divergent_archive_and_status_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shutil.copytree(ROOT / "model", root / "model", ignore=shutil.ignore_patterns("__pycache__"))
            rules = root / "model" / "RULES-REVIEW-EVIDENCE.common.md"
            rules.write_text(
                rules.read_text(encoding="utf-8").replace(
                    '"archive_destination": "ARCHIVED/Reviews/"',
                    '"archive_destination": "ARCHIVED/Reports/"',
                ),
                encoding="utf-8",
            )
            template = root / "model" / "TEMPLATES" / "TEMPLATE.brag-report.common.md"
            template.write_text(
                template.read_text(encoding="utf-8").replace("status: draft", "status: published"),
                encoding="utf-8",
            )

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "review-archive-destination,unknown-review-status",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            [finding["code"] for finding in parsed_json(result)["findings"]],
            ["review-archive-destination", "unknown-review-status"],
        )

    def test_duplicate_evidence_policy_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shutil.copytree(ROOT / "model", root / "model", ignore=shutil.ignore_patterns("__pycache__"))
            task_type = root / "model" / "TASK_TYPES" / "brag-report.common.md"
            task_type.write_text(
                task_type.read_text(encoding="utf-8")
                + "\n```json evidence-ownership\n"
                + '{"schema_version":"agent-brain-evidence-ownership/v1","owner":"model/TASK_TYPES/brag-report.common.md"}'
                + "\n```\n",
                encoding="utf-8",
            )

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "duplicate-policy-owner",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(parsed_json(result)["findings"][0]["code"], "duplicate-policy-owner")


class ContentBoundaryTests(unittest.TestCase):
    def test_repository_documents_satisfy_canonical_content_boundary_contract(self) -> None:
        result = run_cli(
            "--strict",
            "--only",
            "content-boundary,eager-optional-capability",
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(parsed_json(result)["findings"], [])

    def test_orphan_task_and_duplicate_template_policy_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shutil.copytree(ROOT / "model", root / "model", ignore=shutil.ignore_patterns("__pycache__"))
            index = root / "model" / "TASK_TYPES" / "TASK_TYPES.common.md"
            index.write_text(
                index.read_text(encoding="utf-8") + "\n- [[missing-task]] - Missing guide.\n",
                encoding="utf-8",
            )
            template = root / "model" / "TEMPLATES" / "TEMPLATE.issue.common.md"
            template.write_text(
                template.read_text(encoding="utf-8")
                + '\n<!-- content-boundary: {"kind":"policy-owner","policy_id":"policy.file-naming",'
                + '"owner":"model/TEMPLATES/TEMPLATE.issue.common.md"} -->\n',
                encoding="utf-8",
            )

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "missing-task-target,duplicate-policy-owner",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            {finding["code"] for finding in parsed_json(result)["findings"]},
            {"duplicate-policy-owner", "missing-task-target"},
        )

    def test_optional_capabilities_are_not_in_startup_payload(self) -> None:
        result = run_cli(
            "--strict",
            "--only",
            "eager-optional-capability",
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(parsed_json(result)["findings"], [])


class ContextBaselineTests(unittest.TestCase):
    def derived_baseline(self) -> dict[str, object]:
        sys.path.insert(0, str(ROOT / "model" / "SCRIPTS"))
        from model_check_context_baseline import canonical_context_baseline

        model = json.loads(MODEL.read_text(encoding="utf-8"))
        return canonical_context_baseline(ROOT, model)

    def fixture_baseline(self) -> dict[str, object]:
        return json.loads(BASELINE.read_text(encoding="utf-8"))

    def test_derives_canonical_baseline(self) -> None:
        derived = self.derived_baseline()
        fixture = self.fixture_baseline()

        self.assertEqual(derived, fixture)
        self.assertEqual(
            BASELINE.read_bytes(),
            json.dumps(fixture, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
                "utf-8"
            )
            + b"\n",
        )
        self.assertFalse(BASELINE.read_bytes().endswith(b"\n\n"))

    def test_covers_every_predeclared_terminal_including_attachments(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        baseline = self.fixture_baseline()
        scenarios = baseline["scenarios"]

        expected = {
            (row["scenario_id"], row["route_id"], row["terminal"])
            for row in model["route_graph"]
        }
        actual = {
            (row["id"], row["route_id"], row["terminal"])
            for row in scenarios
        }

        self.assertEqual(actual, expected)
        self.assertIn(
            ("scenario.attachments", "rule.attachments", "model/RULES-ATTACHMENTS.common.md"),
            actual,
        )
        self.assertEqual([row["id"] for row in scenarios], sorted(row["id"] for row in scenarios))
        for scenario in scenarios:
            self.assertEqual(
                [segment["ordinal"] for segment in scenario["segments"]],
                list(range(len(scenario["segments"]))),
            )

    def test_digest_file_matches_raw_json(self) -> None:
        raw = BASELINE.read_bytes()
        digest_text = BASELINE_DIGEST.read_text("ascii")

        self.assertRegex(digest_text, r"^[0-9a-f]{64}\n$")
        self.assertEqual(hashlib.sha256(raw).hexdigest() + "\n", digest_text)

    def test_production_validator_accepts_canonical_fixture(self) -> None:
        sys.path.insert(0, str(ROOT / "model" / "SCRIPTS"))
        from model_check_context_validator import validate_context_baseline

        model = json.loads(MODEL.read_text(encoding="utf-8"))
        findings = validate_context_baseline(
            ROOT,
            model,
            BASELINE.read_bytes(),
            BASELINE_DIGEST.read_bytes(),
        )

        self.assertEqual(findings, [])

    def test_future_route_sets_are_equal(self) -> None:
        baseline = self.fixture_baseline()
        report = parsed_json(run_cli("--context-report", "--format", "json"))

        self.assertTrue(report["set_equality"]["valid"])
        self.assertEqual(
            baseline["frozen_route_sets"],
            {
                "route_terminals": report["set_equality"]["route_terminals"],
                "scenario_ids": report["set_equality"]["scenario_ids"],
            },
        )


class SkillDependencyTests(unittest.TestCase):
    FINAL_REFERENCES = (
        "skills/brain/references/constraints.md",
        "skills/brain/references/documentation-and-classification.md",
        "skills/brain/references/session-lifecycle-routing.md",
        "skills/brain/references/tool-catalog.md",
    )

    def test_all_conditional_references_resolve(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        result = run_cli(
            "--strict",
            "--only",
            "missing-skill-reference,unreachable-conditional-artifact",
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(parsed_json(result)["findings"], [])
        self.assertEqual(
            tuple(model["context_contract"]["set_equality"]["future_final_payloads"]),
            self.FINAL_REFERENCES,
        )
        for rel_path in self.FINAL_REFERENCES:
            text = (ROOT / rel_path).read_text(encoding="utf-8")
            self.assertIn("schema_version", text)
            self.assertIn("trigger_rules", text)
            self.assertIn("downstream_rules", text)

    def test_startup_excludes_conditional_references(self) -> None:
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        startup_paths = {
            segment["path"]
            for segment in baseline["budgets"]["startup"]["segments"]
        }

        self.assertTrue(startup_paths)
        self.assertTrue(set(self.FINAL_REFERENCES).isdisjoint(startup_paths))
        self.assertTrue(
            {
                "skills/brain/references/brain-maintenance.md",
                "skills/brain/references/setup-and-attach.md",
                "skills/brain/references/tool-catalog.md",
            }.isdisjoint(startup_paths)
        )

    def test_missing_reference_is_rejected(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "model.json"
            model["future_routes"][0]["final_payloads"] = [
                "skills/brain/references/missing-task15-reference.md"
            ]
            model["future_routes"][0]["final_terminal"] = (
                "skills/brain/references/missing-task15-reference.md"
            )
            model["route_graph"][-4]["terminal"] = (
                "skills/brain/references/missing-task15-reference.md"
            )
            path.write_text(
                json.dumps(model, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            result = run_cli(
                "--model",
                str(path),
                "--strict",
                "--only",
                "missing-skill-reference",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual(findings[0]["code"], "missing-skill-reference")
        self.assertEqual(
            findings[0]["path"],
            "skills/brain/references/missing-task15-reference.md",
        )

    def test_orphan_conditional_artifact_is_rejected(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "model.json"
            artifact = "skills/brain/references/orphan-task15-reference.md"
            model["context_contract"]["conditional_artifacts"].append(artifact)
            path.write_text(
                json.dumps(model, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            result = run_cli(
                "--model",
                str(path),
                "--strict",
                "--only",
                "unreachable-conditional-artifact",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual(findings[0]["code"], "unreachable-conditional-artifact")
        self.assertEqual(findings[0]["path"], artifact)


class ContextBaselineMutationTests(unittest.TestCase):
    def validate(
        self,
        baseline: dict[str, object],
        digest_raw: bytes | None = None,
        final_lf: str = "\n",
    ) -> list[object]:
        sys.path.insert(0, str(ROOT / "model" / "SCRIPTS"))
        from model_check_context_validator import validate_context_baseline

        model = json.loads(MODEL.read_text(encoding="utf-8"))
        raw = json.dumps(
            baseline,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8") + final_lf.encode("ascii")
        digest = digest_raw or (hashlib.sha256(raw).hexdigest() + "\n").encode("ascii")
        return validate_context_baseline(ROOT, model, raw, digest)

    def baseline(self) -> dict[str, object]:
        return json.loads(BASELINE.read_text(encoding="utf-8"))

    def assertFinding(self, findings: list[object], code: str, path: str) -> None:
        pairs = {(finding.code, finding.path) for finding in findings}
        self.assertIn((code, path), pairs)

    def test_rejects_scenario_ordering(self) -> None:
        baseline = self.baseline()
        baseline["scenarios"] = list(reversed(baseline["scenarios"]))

        self.assertFinding(self.validate(baseline), "scenario-order", "$.scenarios")

    def test_rejects_absolute_segment_path(self) -> None:
        baseline = self.baseline()
        baseline["scenarios"][0]["segments"][0]["path"] = "/tmp/body.md"

        self.assertFinding(
            self.validate(baseline),
            "segment-path",
            "$.scenarios[scenario.attachments].segments[0].path",
        )

    def test_rejects_backslash_segment_path(self) -> None:
        baseline = self.baseline()
        baseline["scenarios"][0]["segments"][0]["path"] = "model\\BRAIN.common.md"

        self.assertFinding(
            self.validate(baseline),
            "segment-path",
            "$.scenarios[scenario.attachments].segments[0].path",
        )

    def test_rejects_missing_final_lf(self) -> None:
        baseline = self.baseline()

        self.assertFinding(self.validate(baseline, final_lf=""), "baseline-final-lf", "$")

    def test_rejects_excess_final_lf(self) -> None:
        baseline = self.baseline()

        self.assertFinding(self.validate(baseline, final_lf="\n\n"), "baseline-final-lf", "$")

    def test_rejects_content_hash_mismatch(self) -> None:
        baseline = self.baseline()
        baseline["scenarios"][0]["segments"][0]["sha256"] = "0" * 64

        self.assertFinding(
            self.validate(baseline),
            "segment-sha256",
            "$.scenarios[scenario.attachments].segments[0].sha256",
        )

    def test_rejects_digest_mismatch(self) -> None:
        baseline = self.baseline()

        self.assertFinding(
            self.validate(baseline, digest_raw=("0" * 64 + "\n").encode("ascii")),
            "digest-mismatch",
            "tests/fixtures/model-context-baseline.sha256",
        )

    def test_rejects_duplicate_scenario(self) -> None:
        baseline = self.baseline()
        baseline["scenarios"][1]["id"] = baseline["scenarios"][0]["id"]

        self.assertFinding(self.validate(baseline), "scenario-set", "$.scenarios")

    def test_rejects_missing_scenario(self) -> None:
        baseline = self.baseline()
        baseline["scenarios"].pop()

        self.assertFinding(self.validate(baseline), "scenario-set", "$.scenarios")

    def test_rejects_duplicate_terminal(self) -> None:
        baseline = self.baseline()
        baseline["scenarios"][1]["terminal"] = baseline["scenarios"][0]["terminal"]

        self.assertFinding(self.validate(baseline), "terminal-set", "$.scenarios")

    def test_rejects_missing_terminal(self) -> None:
        baseline = self.baseline()
        baseline["scenarios"][0]["terminal"] = "model/MISSING.common.md"

        self.assertFinding(self.validate(baseline), "terminal-set", "$.scenarios")

    def test_rejects_duplicate_ordinal(self) -> None:
        baseline = self.baseline()
        scenario = baseline["scenarios"][0]
        scenario["segments"].append(dict(scenario["segments"][0]))
        scenario["segments"][1]["ordinal"] = 0

        self.assertFinding(
            self.validate(baseline),
            "segment-ordinal",
            f"$.scenarios[{scenario['id']}].segments",
        )

    def test_rejects_missing_ordinal(self) -> None:
        baseline = self.baseline()
        scenario = baseline["scenarios"][0]
        scenario["segments"].append(dict(scenario["segments"][0]))
        scenario["segments"][1]["ordinal"] = 4

        self.assertFinding(
            self.validate(baseline),
            "segment-ordinal",
            f"$.scenarios[{scenario['id']}].segments",
        )

    def test_rejects_duplicate_agents_injection(self) -> None:
        baseline = self.baseline()
        baseline["budgets"]["startup"]["segments"].append(
            dict(baseline["budgets"]["startup"]["segments"][0])
        )

        self.assertFinding(
            self.validate(baseline),
            "runtime-agents-count",
            "$.budgets.startup.segments",
        )

    def test_rejects_brain_startup_injection(self) -> None:
        baseline = self.baseline()
        injected = dict(baseline["budgets"]["startup"]["segments"][0])
        injected["path"] = "model/BRAIN.common.md"
        baseline["budgets"]["startup"]["segments"].append(injected)

        self.assertFinding(self.validate(baseline), "brain-eager", "$.budgets.startup.segments")

    def test_rejects_terminal_injection(self) -> None:
        baseline = self.baseline()
        baseline["scenarios"][0]["terminal_load_count"] = 2

        self.assertFinding(
            self.validate(baseline),
            "terminal-load-count",
            "$.scenarios[scenario.attachments].terminal_load_count",
        )

    def test_rejects_broad_body_inclusion(self) -> None:
        baseline = self.baseline()
        scenario = next(
            row for row in baseline["scenarios"] if row["id"] == "scenario.constraints"
        )
        injected = dict(baseline["scenarios"][0]["segments"][0])
        injected["ordinal"] = len(scenario["segments"])
        injected["path"] = "model/BRAIN.common.md"
        scenario["segments"].append(injected)

        self.assertFinding(
            self.validate(baseline),
            "broad-body-inclusion",
            "$.scenarios[scenario.constraints].segments",
        )

    def test_rejects_startup_budget_over_75(self) -> None:
        baseline = self.baseline()
        baseline["budgets"]["startup"]["current_bytes"] = (
            baseline["budgets"]["startup"]["cap_bytes"] + 1
        )

        self.assertFinding(
            self.validate(baseline),
            "startup-budget",
            "$.budgets.startup.current_bytes",
        )

    def test_rejects_conditional_budget_over_110(self) -> None:
        baseline = self.baseline()
        scenario_id = sorted(baseline["budgets"]["conditional_scenarios"])[0]
        budget = baseline["budgets"]["conditional_scenarios"][scenario_id]
        budget["current_bytes"] = budget["cap_bytes"] + 1

        self.assertFinding(
            self.validate(baseline),
            "conditional-budget",
            f"$.budgets.conditional_scenarios.{scenario_id}",
        )


class LoadingContractTests(unittest.TestCase):
    def context(self) -> dict[str, object]:
        result = run_cli("--context-report", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        return parsed_json(result)

    def expected_fixture_state(self, session_open: object) -> object:
        return session_open.SessionDigestState(
            mode="dry-run",
            brain_root="/fixture/brain",
            today="2000-01-02",
            today_daily_exists=True,
            latest_daily="2000-01-02.md",
            day_rollover_detected=False,
            session_id="fixture-session",
            runtime="codex",
            cwd="/fixture/project",
            topic="fixture-session",
            session_note="WIP/SESSIONS/2000-01-02-session-fixture-session-fixture-session.md",
            note_action="would-create",
            daily_update="JOURNAL/2000-01-02.md",
            daily_action="would-upsert",
            open_sessions=("WIP/SESSIONS/1999-12-31-session-previous.md",),
            operational_files=(
                ("AGENTS.md", True),
                ("BRAIN.md", True),
                ("WIP/WIP.md", True),
                ("TASK_TYPES/TASK_TYPES.md", True),
            ),
            wip_context=(
                "## Fixture project",
                "  - fixed WIP context for /fixture/project",
            ),
            task_types=("- [[fixture-task]] Fixed task route",),
            injected_project_agents=True,
        )

    def test_context_report_covers_every_route_terminal(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        report = self.context()

        expected = {
            (row["scenario_id"], row["route_id"], row["terminal"])
            for row in model["route_graph"]
        }
        actual = {
            (row["scenario_id"], row["route_id"], row["terminal"])
            for row in report["scenarios"]
        }

        self.assertEqual(actual, expected)
        self.assertEqual(report["totals"]["scenario_count"], 13)
        self.assertEqual(report["totals"]["future_route_count"], 4)

    def test_context_report_enforces_declared_set_equality(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        report = self.context()
        equality = report["set_equality"]

        self.assertTrue(equality["valid"])
        self.assertEqual(
            equality["discovered_conditional_artifacts"],
            model["context_contract"]["conditional_artifacts"],
        )
        self.assertEqual(
            equality["route_terminals"],
            model["context_contract"]["set_equality"]["route_terminals"],
        )
        self.assertEqual(
            equality["scenario_ids"],
            model["context_contract"]["set_equality"]["scenario_ids"],
        )
        self.assertEqual(
            equality["future_temporary_payloads"],
            model["context_contract"]["set_equality"]["future_temporary_payloads"],
        )
        self.assertEqual(
            equality["future_final_payloads"],
            model["context_contract"]["set_equality"]["future_final_payloads"],
        )
        self.assertEqual(
            equality["frozen_baseline_ids"],
            [f"baseline.{model['baseline']['commit']}"],
        )

    def test_corrupt_future_baseline_id_invalidates_set_equality(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "model.json"
            model["future_routes"][0]["baseline_id"] = "baseline.deadbeef"
            path.write_text(json.dumps(model), encoding="utf-8")

            result = run_cli("--model", str(path), "--context-report", "--format", "json")
            report = parsed_json(result)

        mismatch = report["set_equality"]["mismatches"]["future_baseline_ids"]
        self.assertEqual(result.returncode, 0)
        self.assertFalse(report["set_equality"]["valid"])
        self.assertEqual(mismatch["actual"], ["baseline.993247b2850ac86993c7c6dd18e6c4fd9ec6df7c", "baseline.deadbeef"])
        self.assertEqual(mismatch["expected"], ["baseline.993247b2850ac86993c7c6dd18e6c4fd9ec6df7c"])

    def test_future_routes_resolve_to_final_files_after_relocation(self) -> None:
        report = self.context()
        future = [
            row for row in report["scenarios"]
            if row["route_id"].startswith("skill.")
        ]

        self.assertEqual(len(future), 4)
        for scenario in future:
            self.assertTrue(scenario["segment_ids"])
            self.assertEqual(scenario["payload_status"], "current-terminal")
            self.assertEqual(scenario["resolution"], "final-file")
            self.assertGreater(scenario["model_visible_bytes"], 0)
            self.assertEqual(scenario["segment_ids"], [scenario["terminal"]])
            self.assertEqual(scenario["segments"][0]["kind"], "disk-file")
            self.assertRegex(scenario["segments"][0]["sha256"], r"^[0-9a-f]{64}$")

    def test_deterministic_totals_injected_once_and_raw_hashes(self) -> None:
        first = run_cli("--context-report", "--format", "json")
        second = run_cli("--context-report", "--format", "json")
        report = parsed_json(first)

        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(
            report["byte_accounting"]["fixture_session_digest_sha256"],
            report["fixture_session_digest"]["sha256"],
        )
        self.assertEqual(
            report["fixture_session_digest"]["sha256"],
            hashlib.sha256(report["fixture_session_digest"]["text"].encode("utf-8")).hexdigest(),
        )
        injected = [
            segment for segment in report["runtime_segments"]
            if segment["id"] == "runtime.project-agents.injected"
        ]
        self.assertEqual(len(injected), 1)

    def test_disk_reads_are_separate_and_unrelated_bodies_excluded(self) -> None:
        report = self.context()
        daily = next(
            row for row in report["scenarios"]
            if row["scenario_id"] == "scenario.daily-notes"
        )

        self.assertEqual(daily["segment_ids"], ["model/RULES-DAILY-NOTES.common.md"])
        self.assertEqual(daily["disk_reads"], ["model/RULES-DAILY-NOTES.common.md"])
        self.assertIn("model/RULES-LINKS.common.md", daily["excluded_artifacts"])
        self.assertEqual(
            daily["selectivity_delta"]["included"],
            ["model/RULES-DAILY-NOTES.common.md"],
        )

    def test_brain_route_is_conditional(self) -> None:
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        brain_paths = [
            segment["path"]
            for scenario in baseline["scenarios"]
            for segment in scenario["segments"]
            if segment["path"] == "model/BRAIN.common.md"
        ]
        brain_scenario = next(
            scenario
            for scenario in baseline["scenarios"]
            if scenario["id"] == "scenario.brain-structure"
        )
        startup_paths = [
            segment["path"]
            for segment in baseline["budgets"]["startup"]["segments"]
        ]
        attachment_paths = [
            segment["path"]
            for scenario in baseline["scenarios"]
            for segment in scenario["segments"]
            if scenario["id"] == "scenario.attachments"
        ]
        brain_budget = baseline["budgets"]["conditional_scenarios"]["scenario.brain-structure"]

        self.assertEqual(brain_paths, ["model/BRAIN.common.md"])
        self.assertEqual(brain_scenario["route_id"], "model.brain-structure")
        self.assertLessEqual(brain_budget["current_bytes"], brain_budget["cap_bytes"])
        self.assertEqual(attachment_paths, ["model/RULES-ATTACHMENTS.common.md"])
        self.assertNotIn("model/BRAIN.common.md", startup_paths)

    def test_each_route_loads_exactly_one_terminal(self) -> None:
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

        for scenario in baseline["scenarios"]:
            self.assertEqual(scenario["terminal_load_count"], 1)
            terminal_segments = [
                segment
                for segment in scenario["segments"]
                if segment["path"] == scenario["terminal"]
            ]
            if scenario["payload_status"] == "current-terminal":
                self.assertEqual(len(terminal_segments), 1)
            else:
                self.assertEqual(terminal_segments, [])

    def test_session_open_is_unique_authority_in_metadata(self) -> None:
        sys.path.insert(0, str(ROOT / "model" / "SCRIPTS"))
        from model_check_context_payloads import session_authority_contract

        model = json.loads(MODEL.read_text(encoding="utf-8"))
        authority = session_authority_contract(model)

        self.assertEqual(authority["authority"], "skills/brain/scripts/session_open.py")
        self.assertEqual(authority["fallback"], "skills/brain/scripts/session_bootstrap.py")
        self.assertEqual(authority["fallback_role"], "compatibility-fallback")

    def test_session_bootstrap_authority_mutation_is_rejected(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "model.json"
            model["context_contract"]["session_authority"]["authority"] = (
                "skills/brain/scripts/session_bootstrap.py"
            )
            path.write_text(
                json.dumps(model, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            result = run_cli(
                "--model",
                str(path),
                "--strict",
                "--only",
                "session-authority-conflict",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual(findings[0]["code"], "session-authority-conflict")
        self.assertEqual(findings[0]["path"], "model/OPERATING-MODEL.json")

    def test_fixed_session_digest_is_host_independent(self) -> None:
        session_open = load_session_open()
        state = self.expected_fixture_state(session_open)
        rendered = session_open.render_session_digest(state)

        self.assertIn("brain_root: /fixture/brain\n", rendered)
        self.assertIn("today: 2000-01-02\n", rendered)
        self.assertIn("session_id: fixture-session\n", rendered)
        self.assertNotIn(str(ROOT), rendered)
        self.assertNotIn(tempfile.gettempdir(), rendered)
        self.assertEqual(rendered.encode("utf-8").decode("utf-8"), rendered)

    def test_production_collection_matches_pure_renderer_raw_bytes(self) -> None:
        session_open = load_session_open()
        request = session_open.fixed_session_digest_request()
        collected = session_open.collect_session_digest_state(request)
        pure = self.expected_fixture_state(session_open)

        self.assertEqual(collected, pure)
        self.assertEqual(
            session_open.render_session_digest(collected).encode("utf-8"),
            session_open.render_session_digest(pure).encode("utf-8"),
        )

    def test_digest_excludes_instruction_bodies(self) -> None:
        session_open = load_session_open()
        sentinel = "AGENTS_BRAIN_BODY_SENTINEL_TODO17"
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            (brain / "AGENTS.md").write_text(
                f"# AGENTS\n\n{sentinel}\n",
                encoding="utf-8",
            )
            (brain / "BRAIN.md").write_text(
                f"# BRAIN\n\n{sentinel}\n",
                encoding="utf-8",
            )
            wip = brain / "WIP"
            wip.mkdir()
            (wip / "WIP.md").write_text(
                "# WIP\n\n## project\n- visible state-only WIP\n",
                encoding="utf-8",
            )
            task_types = brain / "TASK_TYPES"
            task_types.mkdir()
            (task_types / "TASK_TYPES.md").write_text(
                "- [[runtime-task]] Runtime task one-liner\n",
                encoding="utf-8",
            )

            state = session_open.collect_session_digest_state(
                session_open.SessionDigestRequest(
                    brain_root=str(brain),
                    session_id="session-todo17",
                    runtime="codex",
                    session_label="todo17",
                    cwd="/workspace/project",
                    prepare_daily=False,
                    apply=False,
                    today="2026-07-24",
                )
            )
            rendered = session_open.render_session_digest(state)

        self.assertIn("- AGENTS.md: present", rendered)
        self.assertIn("- BRAIN.md: present", rendered)
        self.assertIn("visible state-only WIP", rendered)
        self.assertNotIn(sentinel, rendered)

    def test_unmatched_task_body_is_not_loaded(self) -> None:
        session_open = load_session_open()
        sentinel = "UNMATCHED_TASK_BODY_SENTINEL_TODO17"
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            task_types = brain / "TASK_TYPES"
            task_types.mkdir()
            (task_types / "TASK_TYPES.md").write_text(
                "- [[runtime-task]] Runtime task one-liner\n"
                "- [[unmatched-private-task]] Unmatched private one-liner\n",
                encoding="utf-8",
            )
            (task_types / "runtime-task.md").write_text(
                "# Runtime task\n\nRuntime task body must stay conditional.\n",
                encoding="utf-8",
            )
            (task_types / "unmatched-private-task.md").write_text(
                f"# Private task\n\n{sentinel}\n",
                encoding="utf-8",
            )

            state = session_open.collect_session_digest_state(
                session_open.SessionDigestRequest(
                    brain_root=str(brain),
                    session_id="session-todo17",
                    runtime="codex",
                    session_label="todo17",
                    cwd="/workspace/runtime-project",
                    prepare_daily=False,
                    apply=False,
                    today="2026-07-24",
                )
            )
            rendered = session_open.render_session_digest(state)

        self.assertIn("- [[runtime-task]] Runtime task one-liner", rendered)
        self.assertIn("- [[unmatched-private-task]] Unmatched private one-liner", rendered)
        self.assertNotIn("Runtime task body must stay conditional", rendered)
        self.assertNotIn(sentinel, rendered)

    def test_fixture_collection_uses_primitive_inputs_not_final_state(self) -> None:
        session_open = load_session_open()
        request = session_open.fixed_session_digest_request()
        self.assertNotIn(
            "injected_state",
            {field.name for field in fields(session_open.SessionDigestRequest)},
        )
        fixture_data = request.fixture_data
        if fixture_data is None:
            raise AssertionError("fixture request must carry primitive fixture data")
        changed = replace(
            fixture_data,
            wip_context=("## Changed fixture project", "  - changed primitive input"),
        )
        changed_request = replace(request, fixture_data=changed)

        original = session_open.render_session_digest(
            session_open.collect_session_digest_state(request)
        )
        rendered = session_open.render_session_digest(
            session_open.collect_session_digest_state(changed_request)
        )

        self.assertNotEqual(rendered.encode("utf-8"), original.encode("utf-8"))
        self.assertIn("Changed fixture project", rendered)

    def test_startup_budget_is_at_most_75_percent(self) -> None:
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        budget = baseline["budgets"]["startup"]

        self.assertEqual(
            budget["cap_formula"],
            "(baseline_bytes*75)//100",
        )
        self.assertLessEqual(budget["current_bytes"], budget["cap_bytes"])

    def test_conditional_budgets_are_at_most_110_percent(self) -> None:
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        budgets = baseline["budgets"]["conditional_scenarios"]

        self.assertEqual(
            baseline["budgets"]["conditional_cap_formula"],
            "(baseline_bytes*110+99)//100",
        )
        for scenario_id, budget in budgets.items():
            self.assertEqual(scenario_id, budget["scenario_id"])
            self.assertLessEqual(budget["current_bytes"], budget["cap_bytes"])


if __name__ == "__main__":
    unittest.main()


def __getattr__(name: str) -> type[unittest.TestCase]:
    if name == "LoadingTraceTests":
        return LoadingContractTests
    if name in {"StrictGateTests", "WorkflowContractTests"}:
        from tests import model_check_todo19_cases

        return getattr(model_check_todo19_cases, name)
    raise AttributeError(name)

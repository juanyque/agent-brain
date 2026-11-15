from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "model" / "SCRIPTS" / "model_check.py"
MODEL = ROOT / "model" / "OPERATING-MODEL.json"
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"


def run_cli(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def parsed_json(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise AssertionError("expected JSON object")
    return value


def copy_repo_fixture(root: Path) -> None:
    shutil.copytree(
        ROOT,
        root,
        ignore=shutil.ignore_patterns(".git", "__pycache__"),
        dirs_exist_ok=True,
    )


def init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "model/OPERATING-MODEL.json"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Todo19",
            "-c",
            "user.email=todo19@example.invalid",
            "commit",
            "-qm",
            "baseline",
        ],
        cwd=root,
        check=True,
    )


def workflow_lines() -> list[str]:
    return WORKFLOW.read_text(encoding="utf-8").splitlines()


@dataclass(frozen=True, slots=True)
class WorkflowJob:
    os: tuple[str, ...]
    steps: tuple[tuple[str, str], ...]

    def step_named(self, name: str) -> str:
        for step_name, body in self.steps:
            if step_name == name:
                return body
        raise AssertionError(f"missing workflow step: {name}")


def stdlib_contracts_job() -> WorkflowJob:
    lines = workflow_lines()
    start = lines.index("  stdlib-contracts:")
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("  ") and not lines[index].startswith("    ")
        ),
        len(lines),
    )
    block = lines[start:end]
    os_line = next(line for line in block if line.strip().startswith("os: ["))
    matrix = os_line.split("[", 1)[1].split("]", 1)[0]
    steps: list[tuple[str, str]] = []
    for index, line in enumerate(block):
        if not line.startswith("      - name: "):
            continue
        name = line.removeprefix("      - name: ")
        step_end = next(
            (
                next_index
                for next_index in range(index + 1, len(block))
                if block[next_index].startswith("      - name: ")
            ),
            len(block),
        )
        steps.append((name, "\n".join(block[index:step_end])))
    return WorkflowJob(
        os=tuple(item.strip() for item in matrix.split(",")),
        steps=tuple(steps),
    )


class StrictGateTests(unittest.TestCase):
    def test_orphan_common_rule_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            copy_repo_fixture(root)
            (root / "model" / "RULES-ORPHAN.common.md").write_text(
                "# Orphan\n",
                encoding="utf-8",
            )

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "orphan-model-artifact",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual(findings[0]["code"], "orphan-model-artifact")
        self.assertEqual(findings[0]["path"], "model/RULES-ORPHAN.common.md")
        self.assertNotIn("unmapped-cluster", {finding["code"] for finding in findings})

    def test_missing_attachment_rule_still_fails_as_unmapped_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            copy_repo_fixture(root)
            (root / "model" / "RULES-ATTACHMENTS.common.md").unlink()

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "unmapped-cluster",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual(findings[0]["code"], "unmapped-cluster")
        self.assertEqual(findings[0]["path"], "model/RULES-ATTACHMENTS.common.md")

    def test_startup_budget_overflow_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            copy_repo_fixture(root)
            baseline = root / "tests" / "fixtures" / "model-context-baseline.json"
            body = json.loads(baseline.read_text(encoding="utf-8"))
            body["budgets"]["startup"]["cap_bytes"] = 1
            baseline.write_text(
                json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "context-budget-exceeded",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual(findings[0]["code"], "context-budget-exceeded")

    def test_untracked_out_of_scope_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "model").mkdir()
            shutil.copy(MODEL, root / "model" / "OPERATING-MODEL.json")
            init_repo(root)
            (root / "private.txt").write_text("out of scope\n", encoding="utf-8")

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "worktree-scope",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertIn("out-of-scope-path", {finding["code"] for finding in findings})

    def test_untracked_whitespace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "model").mkdir()
            shutil.copy(MODEL, root / "model" / "OPERATING-MODEL.json")
            init_repo(root)
            (root / "README.md").write_text("trailing space \n", encoding="utf-8")

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "whitespace",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual(findings[0]["code"], "whitespace-error")
        self.assertIn("README.md", findings[0]["message"])


class WorkflowContractTests(unittest.TestCase):
    def test_resolves_model_base_per_event(self) -> None:
        job = stdlib_contracts_job()
        checkout = job.step_named("Check out repository")
        resolve = job.step_named("Resolve comparison base")

        self.assertIn("fetch-depth: 0", checkout)
        self.assertIn("tests/support/resolve_model_base.sh", resolve)
        self.assertIn("EVENT_NAME: ${{ github.event_name }}", resolve)
        self.assertIn(
            "PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}", resolve
        )
        self.assertIn("PUSH_BEFORE_SHA: ${{ github.event.before }}", resolve)
        self.assertIn(
            "DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}", resolve
        )
        self.assertIn('git cat-file -e "${MODEL_BASE}^{commit}"', resolve)
        self.assertIn('"MODEL_BASE=%s\\n" "$MODEL_BASE" >> "$GITHUB_ENV"', resolve.replace("'", '"'))
        # The base must come from the resolver only: reject any constant pin, however
        # it is spelled, so re-adding one fails here even if the old SHA changes.
        self.assertIn('MODEL_BASE="$(bash tests/support/resolve_model_base.sh)"', resolve)
        self.assertNotRegex(resolve, r"MODEL_BASE[:=]\s*[\"']?[0-9a-f]{7,40}")
        self.assertNotRegex(WORKFLOW.read_text(), r"MODEL_BASE[:=]\s*[\"']?[0-9a-f]{7,40}")
        self.assertNotIn("993247b", resolve)
        self.assertNotIn("993247b", WORKFLOW.read_text())
        self.assertNotIn("rev-list --max-parents=0", resolve)

    def test_macos_and_linux_run_committed_and_worktree_gates(self) -> None:
        job = stdlib_contracts_job()
        self.assertEqual(job.os, ("ubuntu-latest", "macos-latest"))
        committed = job.step_named("Run committed-range gates")
        worktree = job.step_named("Run worktree gates")

        self.assertIn('git diff "${MODEL_BASE}...HEAD" --check', committed)
        self.assertIn(
            ":(exclude)skills/manage-document-projects/assets/project-types/"
            "residential-lease/jurisdictions/**/legal-sources/snapshots/**/raw/**",
            committed,
        )
        self.assertIn(
            ":(exclude)skills/manage-document-projects/assets/project-types/"
            "residential-lease/templates/*.md.j2",
            committed,
        )
        self.assertIn("--git-base", committed)
        self.assertIn("committed-scope", committed)
        self.assertIn("git diff HEAD --check", worktree)
        self.assertIn("worktree-scope,whitespace", worktree)

    def test_macos_and_linux_run_current_tests(self) -> None:
        job = stdlib_contracts_job()
        names = tuple(name for name, _ in job.steps)

        self.assertEqual(job.os, ("ubuntu-latest", "macos-latest"))
        self.assertIn("Run contract and integration tests", names)


def canonical_model() -> dict[str, object]:
    raw = MODEL.read_bytes()
    parsed = json.loads(raw)
    expected = (
        json.dumps(
            parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
        + b"\n"
    )
    if raw != expected:
        raise AssertionError(f"{MODEL} is not canonical JSON")
    return parsed


class OperatingModelContractTests(unittest.TestCase):
    def test_governed_inventory_matches_model_markdown(self) -> None:
        model = canonical_model()
        governed = set(model["governed_inventory"])
        discovered = {
            str(path.relative_to(ROOT))
            for parent in (ROOT, ROOT / "model", ROOT / "skills" / "brain")
            for path in parent.rglob("*.md")
            if parent != ROOT or path.name == "AGENTS.md"
        }
        self.assertEqual(governed, discovered)

    def test_route_graph_has_13_unique_triples_and_linked_skill_routes(self) -> None:
        model = canonical_model()
        routes = model["route_graph"]
        triples = [(r["route_id"], r["scenario_id"], r["terminal"]) for r in routes]

        self.assertEqual(len(triples), 13)
        for index in range(3):
            self.assertEqual(len({triple[index] for triple in triples}), 13)
        skill_routes = {r["route_id"]: r["terminal"] for r in routes if r["route_id"].startswith("skill.")}
        self.assertEqual(
            set(skill_routes),
            {
                "skill.session-routing",
                "skill.documentation",
                "skill.tool-catalog",
                "skill.constraints",
            },
        )
        router = (ROOT / "skills" / "brain" / "SKILL.md").read_text(encoding="utf-8")
        section = router.split("## Conditional Reference Router", 1)[1].split("\n## ", 1)[0]
        for terminal in skill_routes.values():
            self.assertIn(f"`{terminal.removeprefix('skills/brain/')}`", section)
        self.assertEqual(
            sorted(terminal for _route, _scenario, terminal in triples),
            sorted(model["context_contract"]["conditional_artifacts"]),
        )


RETIRED_MANIFEST_KEYS = frozenset(
    {
        "baseline_source_commit",
        "payload_source_ranges",
        "scenario_metadata",
        "set_equality",
        "future_routes",
        "terminal_status",
        "frozen_after_task",
        "planned_materialization_task",
        "startup_baseline_bytes",
        "startup_cap_bytes",
        "startup_current_bytes",
        "digest_sha256",
        "scenario_count",
        "terminal_count",
        "stale_allowlist",
    }
)
RETIRED_TEXT_MARKERS = (
    "materialized-final-payload-task",
    "planned_materialization_task",
    "payload_source_ranges",
    "declared-before-task",
    "frozen_after_task",
)


def manifest_key_paths(value: object, prefix: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.append((str(key), f"{prefix}/{key}"))
            found.extend(manifest_key_paths(child, f"{prefix}/{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(manifest_key_paths(child, f"{prefix}[{index}]"))
    return found


class RetiredManifestKeyGuardTests(unittest.TestCase):
    def test_manifest_has_no_retired_keys_at_any_depth(self) -> None:
        offenders = [
            path
            for key, path in manifest_key_paths(canonical_model())
            if key in RETIRED_MANIFEST_KEYS
        ]
        self.assertEqual(offenders, [])

    def test_manifest_has_no_retired_top_level_baseline_or_status_fields(self) -> None:
        model = canonical_model()
        self.assertNotIn("baseline", model)
        self.assertEqual(
            set(model["context_baseline"]),
            {"path", "digest_path", "schema_version"},
        )
        self.assertNotIn("status", model["stale_reference_contract"])
        self.assertEqual(set(model["scope"]), {"allow", "deny"})

    def test_manifest_scenarios_are_not_carried_by_payload_metadata(self) -> None:
        model = canonical_model()
        for route in model["route_graph"]:
            self.assertEqual(set(route), {"route_id", "scenario_id", "terminal"})

    def test_routed_text_and_manifest_carry_no_retired_markers(self) -> None:
        paths = [
            *sorted((ROOT / "model").rglob("*.md")),
            *sorted((ROOT / "skills" / "brain").rglob("*.md")),
            MODEL,
        ]
        offenders = [
            f"{path.relative_to(ROOT)}: {marker}"
            for path in paths
            for marker in RETIRED_TEXT_MARKERS
            if marker in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_guard_detects_a_reintroduced_key(self) -> None:
        model = canonical_model()
        model["context_contract"]["set_equality"] = {}
        paths = [
            path
            for key, path in manifest_key_paths(model)
            if key in RETIRED_MANIFEST_KEYS
        ]
        self.assertEqual(paths, ["/context_contract/set_equality"])


class BudgetContractTests(unittest.TestCase):
    def run_with_manifest(self, mutate) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "model").mkdir()
            model = json.loads(MODEL.read_text(encoding="utf-8"))
            mutate(model["finding_contract"])
            manifest = root / "model" / "OPERATING-MODEL.json"
            manifest.write_text(
                json.dumps(model, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                + "\n",
                encoding="utf-8",
            )
            return run_cli("--root", str(root), "--model", str(manifest), "--strict")

    def test_budget_selector_is_default_enabled(self) -> None:
        contract = canonical_model()["finding_contract"]
        self.assertIn("context-budget-exceeded", contract["defaults"])
        row = next(r for r in contract["code_metadata"] if r["code"] == "context-budget-exceeded")
        self.assertIs(row["default"], True)
        for code in ("eager-skill-reference", "session-authority-conflict"):
            other = next(r for r in contract["code_metadata"] if r["code"] == code)
            self.assertIs(other["default"], False)
        self.assertNotIn("loading", contract["defaults"])

    def test_manifest_without_budget_selector_is_rejected(self) -> None:
        def drop(contract: dict[str, object]) -> None:
            contract["defaults"].remove("context-budget-exceeded")

        result = self.run_with_manifest(drop)
        self.assertEqual(result.returncode, 2)
        self.assertIn("context-budget-exceeded must be selected by default", result.stderr)

    def test_manifest_with_budget_default_false_is_rejected(self) -> None:
        def disable(contract: dict[str, object]) -> None:
            for row in contract["code_metadata"]:
                if row["code"] == "context-budget-exceeded":
                    row["default"] = False

        result = self.run_with_manifest(disable)
        self.assertEqual(result.returncode, 2)
        self.assertIn("context-budget-exceeded must default true", result.stderr)

    def test_manifest_without_budget_code_entry_is_rejected(self) -> None:
        def remove(contract: dict[str, object]) -> None:
            contract["defaults"].remove("context-budget-exceeded")
            contract["code_metadata"] = [
                r for r in contract["code_metadata"] if r["code"] != "context-budget-exceeded"
            ]
            for family in contract["families"]:
                family["codes"] = [c for c in family["codes"] if c != "context-budget-exceeded"]
            del contract["severity_defaults"]["context-budget-exceeded"]

        result = self.run_with_manifest(remove)
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing required code contract entry: context-budget-exceeded", result.stderr)

    def run_full_copy(self, mutate, startup_cap: int | None = 1) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            copy_repo_fixture(root)
            manifest = root / "model" / "OPERATING-MODEL.json"
            model = json.loads(manifest.read_text(encoding="utf-8"))
            mutate(model["finding_contract"])
            manifest.write_text(
                json.dumps(model, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                + "\n",
                encoding="utf-8",
            )
            if startup_cap is not None:
                baseline = root / "tests" / "fixtures" / "model-context-baseline.json"
                body = json.loads(baseline.read_text(encoding="utf-8"))
                body["budgets"]["startup"]["cap_bytes"] = startup_cap
                baseline.write_text(
                    json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
            return run_cli("--root", str(root), "--strict", "--format", "json")

    def assert_rejected(self, result: subprocess.CompletedProcess[str], message: str) -> None:
        self.assertEqual(result.returncode, 2)
        self.assertIn(message, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_empty_alias_for_budget_selector_is_rejected(self) -> None:
        def alias(contract: dict[str, object]) -> None:
            contract["aliases"]["context-budget-exceeded"] = []

        self.assert_rejected(
            self.run_full_copy(alias), "context-budget-exceeded must be selected by default"
        )

    def test_redirected_alias_for_budget_selector_is_rejected(self) -> None:
        def alias(contract: dict[str, object]) -> None:
            contract["aliases"]["context-budget-exceeded"] = ["duplicate-route-id"]

        self.assert_rejected(
            self.run_full_copy(alias), "context-budget-exceeded must be selected by default"
        )

    def test_budget_severity_below_error_is_rejected(self) -> None:
        for severity in ("warning", "info"):
            with self.subTest(severity=severity):

                def lower(contract: dict[str, object]) -> None:
                    for row in contract["code_metadata"]:
                        if row["code"] == "context-budget-exceeded":
                            row["severity"] = severity

                self.assert_rejected(
                    self.run_full_copy(lower),
                    "context-budget-exceeded must have effective severity error",
                )

    def test_selecting_the_loading_family_keeps_the_budget_enforced(self) -> None:
        def family(contract: dict[str, object]) -> None:
            contract["defaults"].remove("context-budget-exceeded")
            contract["defaults"].append("loading")

        ok = self.run_full_copy(family, startup_cap=None)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        failing = self.run_full_copy(family)
        self.assertEqual(failing.returncode, 1)
        codes = {f["code"] for f in parsed_json(failing)["findings"]}
        self.assertIn("context-budget-exceeded", codes)

    def assert_plain_strict_fails(self, mutate) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            copy_repo_fixture(root)
            baseline = root / "tests" / "fixtures" / "model-context-baseline.json"
            body = json.loads(baseline.read_text(encoding="utf-8"))
            mutate(body["budgets"])
            baseline.write_text(
                json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            result = run_cli("--root", str(root), "--strict", "--format", "json")
            findings = parsed_json(result)["findings"]
        self.assertEqual(result.returncode, 1)
        self.assertEqual({f["code"] for f in findings}, {"context-budget-exceeded"})

    def test_plain_strict_fails_when_startup_exceeds_its_cap(self) -> None:
        def shrink(budgets: dict[str, object]) -> None:
            budgets["startup"]["cap_bytes"] = 1

        self.assert_plain_strict_fails(shrink)

    def test_plain_strict_fails_when_a_scenario_exceeds_its_cap(self) -> None:
        def shrink(budgets: dict[str, object]) -> None:
            scenario = budgets["conditional_scenarios"]["scenario.links"]
            scenario["cap_bytes"] = scenario["current_bytes"] - 1

        self.assert_plain_strict_fails(shrink)


class LoadingUsageErrorOrderingTests(unittest.TestCase):
    """Default strict reports structural findings when loading data is uncomputable."""

    def run_mutated(self, mutate, *args: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            copy_repo_fixture(root)
            mutate(root)
            return run_cli("--root", str(root), "--strict", *args)

    @staticmethod
    def duplicate_scenario(root: Path) -> None:
        manifest = root / "model" / "OPERATING-MODEL.json"
        model = json.loads(manifest.read_text(encoding="utf-8"))
        graph = model["route_graph"]
        graph[1]["scenario_id"] = graph[0]["scenario_id"]
        manifest.write_text(
            json.dumps(model, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def delete_terminal(root: Path) -> None:
        (root / "model" / "RULES-LINKS.common.md").unlink()

    @staticmethod
    def delete_fixture(root: Path) -> None:
        (root / "tests" / "fixtures" / "model-context-baseline.json").unlink()

    @staticmethod
    def duplicate_and_shrink_cap(root: Path) -> None:
        LoadingUsageErrorOrderingTests.duplicate_scenario(root)
        path = root / "tests" / "fixtures" / "model-context-baseline.json"
        body = json.loads(path.read_text(encoding="utf-8"))
        scenario = body["budgets"]["conditional_scenarios"]["scenario.links"]
        scenario["cap_bytes"] = scenario["current_bytes"] - 1
        path.write_text(
            json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    def test_default_strict_reports_duplicate_scenario_id(self) -> None:
        result = self.run_mutated(self.duplicate_scenario, "--format", "json")
        self.assertEqual(result.returncode, 1)
        codes = {f["code"] for f in parsed_json(result)["findings"]}
        self.assertIn("duplicate-route-id", codes)

    def test_default_strict_reports_deleted_terminal(self) -> None:
        result = self.run_mutated(self.delete_terminal, "--format", "json")
        self.assertEqual(result.returncode, 1)
        codes = {f["code"] for f in parsed_json(result)["findings"]}
        self.assertIn("missing-route-target", codes)

    def test_default_strict_without_fixture_and_other_errors_is_a_usage_error(self) -> None:
        result = self.run_mutated(self.delete_fixture)
        self.assertEqual(result.returncode, 2)
        self.assertIn("context baseline fixture is unavailable", result.stderr)

    def test_only_budget_selector_never_swallows_the_usage_error(self) -> None:
        result = self.run_mutated(
            self.duplicate_scenario, "--only", "context-budget-exceeded"
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("route_graph scenario_id must be unique", result.stderr)

    def test_default_strict_with_duplicate_and_exceeded_cap_fails(self) -> None:
        result = self.run_mutated(self.duplicate_and_shrink_cap, "--format", "json")
        self.assertEqual(result.returncode, 1)
        codes = {f["code"] for f in parsed_json(result)["findings"]}
        self.assertIn("duplicate-route-id", codes)


class TrackedTextWhitespaceTests(unittest.TestCase):
    def test_tracked_markdown_and_jinja_files_carry_no_trailing_whitespace(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        listing = subprocess.run(
            ["git", "ls-files", "--", "*.md", "*.j2"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=True,
        )
        offenders: list[str] = []
        for rel in listing.stdout.splitlines():
            for lineno, line in enumerate(
                (repo_root / rel).read_text(encoding="utf-8", errors="replace").splitlines(),
                start=1,
            ):
                if line != line.rstrip(" \t"):
                    offenders.append(f"{rel}:{lineno}")
        self.assertEqual(
            offenders,
            [],
            "trailing whitespace reintroduced (git diff --check would fail on "
            "any future diff touching these lines)",
        )


if __name__ == "__main__":
    unittest.main()

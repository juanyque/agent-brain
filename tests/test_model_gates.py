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


HISTORY_SCAFFOLDING_MARKERS = ("agent-brain-reference", "Copied Source Ranges")


def history_scaffolding_findings(payloads: dict[str, str]) -> list[str]:
    """Return "path: marker" for each scaffolding marker found in a payload text."""
    return [
        f"{path}: {marker}"
        for path, text in sorted(payloads.items())
        for marker in HISTORY_SCAFFOLDING_MARKERS
        if marker in text
    ]


def route_terminal_payloads() -> dict[str, str]:
    terminals = {row["terminal"] for row in canonical_model()["route_graph"]}
    return {
        terminal: (ROOT / terminal).read_text(encoding="utf-8")
        for terminal in sorted(terminals)
    }


class HistoryScaffoldingGuardTests(unittest.TestCase):
    REFERENCES = (
        "skills/brain/references/constraints.md",
        "skills/brain/references/documentation-and-classification.md",
        "skills/brain/references/session-lifecycle-routing.md",
        "skills/brain/references/tool-catalog.md",
    )

    def test_route_terminals_carry_no_history_scaffolding(self) -> None:
        payloads = route_terminal_payloads()
        self.assertEqual(len(payloads), 13)
        self.assertEqual(history_scaffolding_findings(payloads), [])

    def test_each_marker_injected_into_a_terminal_is_detected_separately(self) -> None:
        payloads = route_terminal_payloads()
        target = sorted(payloads)[0]
        for marker in HISTORY_SCAFFOLDING_MARKERS:
            with self.subTest(marker=marker):
                injected = {**payloads, target: payloads[target] + f"\n{marker}\n"}
                self.assertEqual(
                    history_scaffolding_findings(injected), [f"{target}: {marker}"]
                )

    def test_marker_outside_a_payload_is_not_flagged(self) -> None:
        payloads = route_terminal_payloads()
        outside = {"README.md": "mentions agent-brain-reference and Copied Source Ranges"}
        self.assertEqual(history_scaffolding_findings(payloads), [])
        self.assertEqual(
            history_scaffolding_findings({**payloads, **outside}),
            [
                "README.md: agent-brain-reference",
                "README.md: Copied Source Ranges",
            ],
        )

    def test_reintroduced_header_in_each_reference_file_is_detected(self) -> None:
        payloads = route_terminal_payloads()
        for rel_path in self.REFERENCES:
            with self.subTest(path=rel_path):
                self.assertIn(rel_path, payloads)
                header = '<!-- agent-brain-reference\n{"downstream_rules":[]}\n-->\n\n'
                text = payloads[rel_path]
                title, _, rest = text.partition("\n\n")
                injected = {**payloads, rel_path: f"{title}\n\n{header}{rest}"}
                self.assertEqual(
                    history_scaffolding_findings(injected),
                    [f"{rel_path}: agent-brain-reference"],
                )


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
        codes = {f["code"] for f in findings}
        # A tampered cap is also a stale fixture: the fixture no longer matches the harness.
        self.assertIn("context-budget-exceeded", codes)
        self.assertLessEqual(codes, {"context-budget-exceeded", "context-baseline-stale"})

    def test_plain_strict_fails_when_startup_exceeds_its_cap(self) -> None:
        def shrink(budgets: dict[str, object]) -> None:
            budgets["startup"]["cap_bytes"] = 1

        self.assert_plain_strict_fails(shrink)

    def test_plain_strict_fails_when_a_scenario_exceeds_its_cap(self) -> None:
        def shrink(budgets: dict[str, object]) -> None:
            scenario = budgets["conditional_scenarios"]["scenario.links"]
            scenario["cap_bytes"] = scenario["current_bytes"] - 1

        self.assert_plain_strict_fails(shrink)


class StaleBaselineContractTests(unittest.TestCase):
    """Plain strict notices a context fixture that no longer matches the loaded text."""

    CODE = "context-baseline-stale"
    FIXTURE = "tests/fixtures/model-context-baseline.json"
    LINKS = "model/RULES-LINKS.common.md"

    @staticmethod
    def write_manifest(root: Path, model: dict[str, object]) -> None:
        (root / "model" / "OPERATING-MODEL.json").write_text(
            json.dumps(model, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    def run_copy(self, mutate, *args: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            copy_repo_fixture(root)
            mutate(root)
            return run_cli("--root", str(root), "--strict", "--format", "json", *args)

    def shrink_terminal(self, root: Path) -> None:
        path = root / self.LINKS
        before = path.read_bytes()
        after = before.replace(b"the ", b"", 1)
        assert len(after) < len(before)
        path.write_bytes(after)

    def rewrite_fixture(self, root: Path, mutate) -> None:
        path = root / self.FIXTURE
        body = json.loads(path.read_text(encoding="utf-8"))
        mutate(body)
        path.write_text(
            json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    def edit_contract(self, mutate):
        def apply(root: Path) -> None:
            manifest = root / "model" / "OPERATING-MODEL.json"
            model = json.loads(manifest.read_text(encoding="utf-8"))
            mutate(model["finding_contract"])
            self.write_manifest(root, model)
            self.shrink_terminal(root)

        return apply

    def stale_findings(self, result: subprocess.CompletedProcess[str]) -> list[dict[str, object]]:
        return [f for f in parsed_json(result)["findings"] if f["code"] == self.CODE]

    def test_manifest_declares_the_stale_code_like_the_budget_code(self) -> None:
        contract = canonical_model()["finding_contract"]
        self.assertIn(self.CODE, contract["defaults"])
        self.assertEqual(contract["severity_defaults"][self.CODE], "error")
        rows = {r["code"]: r for r in contract["code_metadata"]}
        stale, budget = rows[self.CODE], rows["context-budget-exceeded"]
        self.assertEqual({k: v for k, v in stale.items() if k != "code"},
                         {k: v for k, v in budget.items() if k != "code"})
        for code in ("eager-skill-reference", "session-authority-conflict"):
            self.assertIs(rows[code]["default"], False)

    def test_real_repository_passes_plain_strict(self) -> None:
        result = run_cli("--strict", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(parsed_json(result)["findings"], [])

    def test_plain_strict_reports_a_shrunk_terminal_with_an_unregenerated_fixture(self) -> None:
        result = self.run_copy(self.shrink_terminal)
        self.assertEqual(result.returncode, 1)
        findings = parsed_json(result)["findings"]
        self.assertEqual({f["code"] for f in findings}, {self.CODE})
        text = " ".join(str(f["message"]) for f in findings)
        self.assertIn("baseline-derived-mismatch", text)
        self.assertIn("scenarios[scenario.links]", text)
        self.assertTrue(all(f["path"] == self.FIXTURE for f in findings))

    def test_only_selector_reports_the_same_stale_fixture(self) -> None:
        result = self.run_copy(self.shrink_terminal, "--only", self.CODE)
        self.assertEqual(result.returncode, 1)
        self.assertIn("scenarios[scenario.links]", str(self.stale_findings(result)))

    def test_only_selector_passes_on_a_clean_copy(self) -> None:
        result = self.run_copy(lambda root: None, "--only", self.CODE)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tampered_scenario_hash_is_reported(self) -> None:
        def tamper(root: Path) -> None:
            self.rewrite_fixture(root, lambda body: body["scenarios"][0].__setitem__("sha256", "0" * 64))

        result = self.run_copy(tamper)
        self.assertEqual(result.returncode, 1)
        self.assertIn("sha256", str(self.stale_findings(result)))

    def test_tampered_segment_content_is_reported(self) -> None:
        def tamper(root: Path) -> None:
            def mutate(body: dict[str, object]) -> None:
                body["scenarios"][0]["segments"][0]["content"] += "x"

            self.rewrite_fixture(root, mutate)

        result = self.run_copy(tamper)
        self.assertEqual(result.returncode, 1)
        self.assertIn("segment-sha256", str(self.stale_findings(result)))

    def test_stale_sidecar_digest_is_reported_with_its_own_path(self) -> None:
        def tamper(root: Path) -> None:
            (root / "tests" / "fixtures" / "model-context-baseline.sha256").write_text(
                "0" * 64 + "\n", encoding="utf-8"
            )

        result = self.run_copy(tamper)
        self.assertEqual(result.returncode, 1)
        paths = {f["path"] for f in self.stale_findings(result)}
        self.assertEqual(paths, {"tests/fixtures/model-context-baseline.sha256"})

    def test_every_validator_finding_is_reported(self) -> None:
        def tamper(root: Path) -> None:
            def mutate(body: dict[str, object]) -> None:
                body["scenarios"][0]["segments"][0]["content"] += "x"
                body["budgets"]["startup"]["cap_bytes"] = 1

            self.rewrite_fixture(root, mutate)

        result = self.run_copy(tamper)
        internal = {str(f["target"]).split(" ")[0] for f in self.stale_findings(result)}
        self.assertLessEqual(
            {"digest-mismatch", "segment-sha256", "startup-budget", "baseline-derived-mismatch"},
            internal,
        )

    def assert_rejected(self, mutate, message: str) -> None:
        result = self.run_copy(self.edit_contract(mutate))
        self.assertEqual(result.returncode, 2)
        self.assertIn(message, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_stale_code_removed_from_defaults_is_rejected(self) -> None:
        self.assert_rejected(
            lambda c: c["defaults"].remove(self.CODE), f"{self.CODE} must be selected by default"
        )

    def test_empty_alias_is_rejected(self) -> None:
        self.assert_rejected(
            lambda c: c["aliases"].__setitem__(self.CODE, []),
            f"{self.CODE} must be selected by default",
        )

    def test_redirected_alias_is_rejected(self) -> None:
        self.assert_rejected(
            lambda c: c["aliases"].__setitem__(self.CODE, ["duplicate-route-id"]),
            f"{self.CODE} must be selected by default",
        )

    def test_lower_severity_is_rejected(self) -> None:
        for severity in ("warning", "info"):
            with self.subTest(severity=severity):

                def lower(c: dict[str, object]) -> None:
                    for row in c["code_metadata"]:
                        if row["code"] == self.CODE:
                            row["severity"] = severity

                self.assert_rejected(lower, f"{self.CODE} must have effective severity error")

    def test_default_false_is_rejected(self) -> None:
        def disable(c: dict[str, object]) -> None:
            for row in c["code_metadata"]:
                if row["code"] == self.CODE:
                    row["default"] = False

        self.assert_rejected(disable, f"{self.CODE} must default true")

    def test_selecting_the_loading_family_still_detects_a_stale_fixture(self) -> None:
        def family(c: dict[str, object]) -> None:
            c["defaults"].remove(self.CODE)
            c["defaults"].remove("context-budget-exceeded")
            c["defaults"].append("loading")

        result = self.run_copy(self.edit_contract(family))
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.stale_findings(result))

    def test_code_moved_to_another_family_is_rejected(self) -> None:
        budget = "context-budget-exceeded"
        for codes in ((self.CODE,), (budget,), (self.CODE, budget)):
            for family in ("audience", "route-target"):
                for startup_cap in (None, 1):
                    with self.subTest(codes=codes, family=family, startup_cap=startup_cap):

                        def move(c: dict[str, object]) -> None:
                            for row in c["code_metadata"]:
                                if row["code"] in codes:
                                    row["family"] = family

                        def mutate(root: Path) -> None:
                            self.edit_contract(move)(root)
                            if startup_cap is not None:
                                self.rewrite_fixture(
                                    root,
                                    lambda body: body["budgets"]["startup"].__setitem__(
                                        "cap_bytes", startup_cap
                                    ),
                                )

                        result = self.run_copy(mutate)
                        self.assertEqual(result.returncode, 2)
                        self.assertIn("must have effective family loading", result.stderr)
                        self.assertNotIn("Traceback", result.stderr)

    def assert_no_crash(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertNotIn("internal error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn(result.returncode, (1, 2))

    def test_malformed_scenario_segments_are_a_finding_not_a_crash(self) -> None:
        for value in (None, 42, "x", {}, [1, "a", None]):
            with self.subTest(value=value):

                def tamper(root: Path) -> None:
                    self.rewrite_fixture(
                        root, lambda body: body["scenarios"][0].__setitem__("segments", value)
                    )

                result = self.run_copy(tamper, "--only", self.CODE)
                self.assert_no_crash(result)
                if not isinstance(value, list):
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("segment-shape", str(self.stale_findings(result)))

    def test_malformed_fixture_fields_never_crash_the_checker(self) -> None:
        shapes = (None, 42, "x", [1, "a", None], {})
        fields = (
            ("scenarios",),
            ("scenarios", 0),
            ("scenarios", 0, "terminal_load_count"),
            ("scenarios", 0, "id"),
            ("scenarios", 0, "segments", 0),
            ("scenarios", 0, "segments", 0, "path"),
            ("scenarios", 0, "segments", 0, "content"),
            ("scenarios", 0, "segments", 0, "ordinal"),
            ("budgets",),
            ("budgets", "startup"),
            ("budgets", "startup", "segments"),
            ("budgets", "startup", "segments", 0),
            ("budgets", "startup", "cap_bytes"),
            ("budgets", "conditional_scenarios"),
            ("budgets", "conditional_scenarios", "scenario.links"),
            ("frozen_route_sets",),
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            copy_repo_fixture(root)
            path = root / self.FIXTURE
            original = json.loads(path.read_text(encoding="utf-8"))
            for field in fields:
                for shape in shapes:
                    body = json.loads(json.dumps(original))
                    target = body
                    for key in field[:-1]:
                        target = target[key]
                    target[field[-1]] = shape
                    path.write_text(
                        json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n",
                        encoding="utf-8",
                    )
                    for args in (("--only", self.CODE), ()):
                        with self.subTest(field=field, shape=shape, args=args):
                            result = run_cli("--root", str(root), "--strict", *args)
                            self.assert_no_crash(result)

    def test_fixture_and_sidecar_paths_come_from_the_manifest(self) -> None:
        moved = "tests/fixtures/moved/context.json"
        moved_digest = "tests/fixtures/moved/context.digest"

        def relocate(root: Path) -> None:
            (root / "tests" / "fixtures" / "moved").mkdir()
            (root / self.FIXTURE).rename(root / moved)
            (root / "tests" / "fixtures" / "model-context-baseline.sha256").rename(
                root / moved_digest
            )
            manifest = root / "model" / "OPERATING-MODEL.json"
            model = json.loads(manifest.read_text(encoding="utf-8"))
            model["context_baseline"]["path"] = moved
            model["context_baseline"]["digest_path"] = moved_digest
            self.write_manifest(root, model)

        clean = self.run_copy(relocate)
        self.assertEqual(clean.returncode, 0, clean.stderr)

        def stale(root: Path) -> None:
            relocate(root)
            self.shrink_terminal(root)
            (root / moved_digest).write_text("0" * 64 + "\n", encoding="utf-8")

        result = self.run_copy(stale)
        self.assertEqual(result.returncode, 1)
        paths = {f["path"] for f in self.stale_findings(result)}
        self.assertEqual(paths, {moved, moved_digest})

    def test_stale_fixture_with_a_duplicate_scenario_still_reports_the_route_finding(self) -> None:
        def mutate(root: Path) -> None:
            self.shrink_terminal(root)
            LoadingUsageErrorOrderingTests.duplicate_scenario(root)

        result = self.run_copy(mutate)
        self.assertEqual(result.returncode, 1)
        codes = {f["code"] for f in parsed_json(result)["findings"]}
        self.assertIn("duplicate-route-id", codes)

    def test_missing_fixture_is_a_usage_error(self) -> None:
        result = self.run_copy(LoadingUsageErrorOrderingTests.delete_fixture)
        self.assertEqual(result.returncode, 2)
        self.assertIn("context baseline fixture is unavailable", result.stderr)

    def test_missing_digest_sidecar_is_a_usage_error(self) -> None:
        def delete(root: Path) -> None:
            (root / "tests" / "fixtures" / "model-context-baseline.sha256").unlink()

        result = self.run_copy(delete)
        self.assertEqual(result.returncode, 2)
        self.assertIn("context baseline fixture is unavailable", result.stderr)

    def test_only_selector_with_an_invalid_route_graph_is_a_usage_error(self) -> None:
        result = self.run_copy(
            LoadingUsageErrorOrderingTests.duplicate_scenario, "--only", self.CODE
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("route_graph scenario_id must be unique", result.stderr)


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


class UnreadableTerminalTests(unittest.TestCase):
    """An invalid or unreadable terminal or rule file is a finding or a usage error, never exit 3."""

    DAILY = "model/RULES-DAILY-NOTES.common.md"
    LIFECYCLE = "model/RULES-SESSION-LIFECYCLE.common.md"
    LINKS = "model/RULES-LINKS.common.md"

    def run_mutated(self, mutate, *args: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            copy_repo_fixture(root)
            mutate(root)
            return run_cli("--root", str(root), *args)

    @staticmethod
    def delete(rel: str):
        return lambda root: (root / rel).unlink()

    @staticmethod
    def make_directory(rel: str):
        def mutate(root: Path) -> None:
            (root / rel).unlink()
            (root / rel).mkdir()

        return mutate

    @staticmethod
    def invalid_utf8(rel: str):
        def mutate(root: Path) -> None:
            path = root / rel
            path.write_bytes(path.read_bytes() + b"\n\xff\xfe\x80\n")

        return mutate

    def assert_no_crash(self, result: subprocess.CompletedProcess[str]) -> None:
        output = result.stdout + result.stderr
        self.assertNotIn("internal error", output)
        self.assertNotIn("Traceback", output)

    def assert_usage_error(self, result: subprocess.CompletedProcess[str], rel: str) -> None:
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("usage/metadata error", result.stderr)
        self.assertIn(rel, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assert_no_crash(result)

    def test_deleted_daily_notes_rule_is_a_usage_error(self) -> None:
        for extra in ((), ("--format", "json")):
            with self.subTest(extra=extra):
                result = self.run_mutated(self.delete(self.DAILY), "--strict", *extra)
                self.assert_usage_error(result, self.DAILY)

    def test_daily_notes_rule_as_directory_is_a_usage_error(self) -> None:
        result = self.run_mutated(self.make_directory(self.DAILY), "--strict")
        self.assert_usage_error(result, self.DAILY)

    def test_deleted_lifecycle_rule_is_a_usage_error(self) -> None:
        for extra in ((), ("--format", "json")):
            with self.subTest(extra=extra):
                result = self.run_mutated(self.delete(self.LIFECYCLE), "--strict", *extra)
                self.assert_usage_error(result, self.LIFECYCLE)

    def test_links_rule_as_directory_is_a_usage_error_under_plain_strict(self) -> None:
        for extra in ((), ("--format", "json")):
            with self.subTest(extra=extra):
                result = self.run_mutated(self.make_directory(self.LINKS), "--strict", *extra)
                self.assert_usage_error(result, self.LINKS)

    def test_links_rule_as_directory_is_a_missing_route_target_finding(self) -> None:
        for extra in (("--format", "json"), ()):
            with self.subTest(extra=extra):
                result = self.run_mutated(
                    self.make_directory(self.LINKS),
                    "--strict",
                    "--only",
                    "missing-route-target",
                    *extra,
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assert_no_crash(result)
                self.assertIn("missing-route-target", result.stdout)
                self.assertIn(self.LINKS, result.stdout)
                self.assertIn("route terminal is missing or unreadable", result.stdout)

    def test_links_rule_as_directory_never_passes_the_budget_check(self) -> None:
        result = self.run_mutated(
            self.make_directory(self.LINKS), "--strict", "--only", "context-budget-exceeded"
        )
        self.assert_usage_error(result, self.LINKS)

    def test_terminal_with_invalid_utf8_is_a_missing_route_target_finding(self) -> None:
        result = self.run_mutated(
            self.invalid_utf8(self.LINKS),
            "--strict",
            "--only",
            "missing-route-target",
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assert_no_crash(result)
        findings = parsed_json(result)["findings"]
        self.assertEqual(
            [(f["code"], f["path"]) for f in findings], [("missing-route-target", self.LINKS)]
        )

    def test_terminal_with_invalid_utf8_is_a_usage_error_under_plain_strict(self) -> None:
        result = self.run_mutated(self.invalid_utf8(self.LINKS), "--strict")
        self.assert_usage_error(result, self.LINKS)
        self.assertIn("codec can't decode", result.stderr)

    def test_unreadable_terminal_permission_denied_is_never_an_internal_error(self) -> None:
        def deny(root: Path) -> None:
            (root / self.LINKS).chmod(0)

        with tempfile.TemporaryDirectory() as probe_raw:
            probe = Path(probe_raw) / "probe"
            probe.write_text("x", encoding="utf-8")
            probe.chmod(0)
            try:
                probe.read_text(encoding="utf-8")
            except PermissionError:
                pass
            else:
                self.skipTest("host ignores file permissions (for example running as root)")
        # The report digest needs every Markdown file, so even a narrow selector cannot
        # produce a result: the unreadable file is a usage error, never an internal error.
        for extra in (
            ("--strict",),
            ("--strict", "--format", "json"),
            ("--strict", "--only", "missing-route-target"),
        ):
            with self.subTest(extra=extra):
                result = self.run_mutated(deny, *extra)
                self.assert_usage_error(result, self.LINKS)
                self.assertIn("Permission denied", result.stderr)

    def test_missing_common_route_table_is_a_usage_error(self) -> None:
        rel = "model/AGENTS.common.md"
        result = self.run_mutated(self.delete(rel), "--strict")
        self.assert_usage_error(result, rel)


class UnreadableRuleFileTests(unittest.TestCase):
    """Mandatory rule files that a narrow check reads never pass silently or crash."""

    INDEX = "model/TASK_TYPES/TASK_TYPES.common.md"
    SCRIPTS_README = "model/SCRIPTS/README.scripts.common.md"
    BRAIN = "model/BRAIN.common.md"
    CONSTRAINTS = "skills/brain/references/constraints.md"

    def run_mutated(self, mutate, *args: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            copy_repo_fixture(root)
            mutate(root)
            return run_cli("--root", str(root), *args)

    def assert_no_crash(self, result: subprocess.CompletedProcess[str]) -> None:
        output = result.stdout + result.stderr
        self.assertNotIn("internal error", output)
        self.assertNotIn("Traceback", output)

    def assert_usage_error(self, result: subprocess.CompletedProcess[str], rel: str) -> None:
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("usage/metadata error", result.stderr)
        self.assertIn(rel, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assert_no_crash(result)

    def test_missing_task_type_index_is_a_usage_error_under_plain_strict(self) -> None:
        result = self.run_mutated(lambda root: (root / self.INDEX).unlink(), "--strict")
        self.assert_usage_error(result, self.INDEX)

    def test_invalid_utf8_in_scripts_readme_is_a_usage_error_for_git_authority(self) -> None:
        def mutate(root: Path) -> None:
            path = root / self.SCRIPTS_README
            path.write_bytes(path.read_bytes() + b"\n\xff\xfe\x80\n")

        result = self.run_mutated(mutate, "--strict", "--only", "git-authority-explicit")
        self.assert_usage_error(result, self.SCRIPTS_README)

    def test_missing_common_agents_file_is_a_usage_error_for_git_authority(self) -> None:
        rel = "model/AGENTS.common.md"
        result = self.run_mutated(
            lambda root: (root / rel).unlink(), "--strict", "--only", "git-authority-explicit"
        )
        self.assert_usage_error(result, rel)

    def test_missing_brain_guide_is_a_usage_error_for_policy_owner_check(self) -> None:
        result = self.run_mutated(
            lambda root: (root / self.BRAIN).unlink(),
            "--strict",
            "--only",
            "misplaced-policy-owner",
        )
        self.assert_usage_error(result, self.BRAIN)

    def test_undecodable_skill_reference_is_a_missing_skill_reference_finding(self) -> None:
        def mutate(root: Path) -> None:
            path = root / self.CONSTRAINTS
            path.write_bytes(path.read_bytes() + b"\n\xff\xfe\x80\n")

        result = self.run_mutated(
            mutate, "--strict", "--only", "missing-skill-reference", "--format", "json"
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assert_no_crash(result)
        findings = parsed_json(result)["findings"]
        # One finding per skill route that shares this terminal.
        self.assertTrue(findings)
        self.assertEqual(
            {(f["code"], f["path"]) for f in findings},
            {("missing-skill-reference", self.CONSTRAINTS)},
        )
        self.assertIn("missing or unreadable", findings[0]["message"])


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

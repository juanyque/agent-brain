from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "model" / "OPERATING-MODEL.json"
COMMON_AGENTS = ROOT / "model" / "AGENTS.common.md"
BASELINE = ROOT / "tests" / "fixtures" / "model-context-baseline.json"
BASELINE_DIGEST = ROOT / "tests" / "fixtures" / "model-context-baseline.sha256"
SCRIPTS = ROOT / "model" / "SCRIPTS"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class OwnershipContractCases(unittest.TestCase):
    def model(self) -> dict[str, object]:
        return json.loads(MODEL.read_text(encoding="utf-8"))

    def test_all_declared_routes_have_parseable_common_rows_and_resolve_targets(self) -> None:
        from model_check_routes import resolved_route_table

        routes = resolved_route_table(ROOT, self.model(), COMMON_AGENTS)
        actual = {(route.route_id, route.scenario_id) for route in routes}
        expected = {
            ("rule.attachments", "scenario.attachments"),
            ("rule.daily-notes", "scenario.daily-notes"),
            ("rule.file-naming", "scenario.file-operations"),
            ("rule.issue-docs", "scenario.issue-work"),
            ("rule.links", "scenario.links"),
            ("rule.optional-capabilities", "scenario.optional-capability"),
            ("rule.review-evidence", "scenario.review-evidence"),
            ("rule.session-lifecycle", "scenario.session-lifecycle"),
            ("task-types.index", "scenario.task-types"),
        }

        self.assertEqual(actual, expected)
        self.assertEqual({route.load for route in routes if route.route_id == "rule.attachments"}, {"model/RULES-ATTACHMENTS.common.md"})

    def test_temporary_attachment_payload_fixture_resolves_brain_ranges(self) -> None:
        from model_check_routes import resolved_route_table

        model = self.model()
        model["route_graph"] = [
            {
                "route_id": "rule.attachments",
                "scenario_id": "scenario.attachments",
                "terminal": "model/RULES-ATTACHMENTS.common.md",
            }
        ]
        model["context_contract"]["scenario_metadata"] = [
            {
                "id": "scenario.attachments",
                "payload_status": "temporary-ranges-until-materialized",
                "temporary_payloads": [
                    "model/BRAIN.common.md:198-207",
                    "model/BRAIN.common.md:245",
                    "model/BRAIN.common.md:262",
                ],
            }
        ]

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "model").mkdir()
            common = root / "model" / "AGENTS.common.md"
            common.write_text(
                "# AGENTS.common.md\n\n"
                "## Rule triggers\n\n"
                "| Route | Scenario | Trigger | Load |\n"
                "|---|---|---|---|\n"
                "| rule.attachments | scenario.attachments | Creating, moving, auditing, or repairing attachments | model/BRAIN.common.md:198-207; model/BRAIN.common.md:245; model/BRAIN.common.md:262 |\n",
                encoding="utf-8",
            )

            routes = resolved_route_table(root, model, common)

        self.assertEqual([(route.route_id, route.scenario_id, route.load) for route in routes], [("rule.attachments", "scenario.attachments", "model/BRAIN.common.md:198-207; model/BRAIN.common.md:245; model/BRAIN.common.md:262")])

    def test_attachment_rule_is_canonical_destination(self) -> None:
        from model_check_routes import resolved_route_table

        routes = resolved_route_table(ROOT, self.model(), COMMON_AGENTS)

        self.assertEqual({route.load for route in routes if route.route_id == "rule.attachments"}, {"model/RULES-ATTACHMENTS.common.md"})

    def test_missing_attachment_destination_is_rejected_as_unmapped_cluster(self) -> None:
        from model_check_routes import route_target_findings

        model = self.model()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shutil.copytree(ROOT / "model", root / "model")
            common_agents = root / "model" / "AGENTS.common.md"
            (root / "model" / "RULES-ATTACHMENTS.common.md").unlink()

            findings = route_target_findings(root, model, common_agents)

        self.assertEqual([finding.code for finding in findings], ["unmapped-cluster"])
        self.assertEqual(findings[0].path, "model/RULES-ATTACHMENTS.common.md")

    def test_missing_route_target_is_rejected_with_contract_code(self) -> None:
        from model_check_routes import route_target_findings

        model = self.model()
        model["route_graph"] = [
            *model["route_graph"],
            {
                "route_id": "rule.missing",
                "scenario_id": "scenario.missing",
                "terminal": "model/RULES-MISSING.common.md",
            },
        ]

        findings = route_target_findings(ROOT, model, COMMON_AGENTS)

        self.assertEqual([finding.code for finding in findings], ["missing-route-target"])
        self.assertEqual(findings[0].path, "model/RULES-MISSING.common.md")

    def test_common_git_authority_requires_explicit_git_authorization(self) -> None:
        from model_check_routes import git_authority

        authority = git_authority(COMMON_AGENTS)

        self.assertEqual(authority.git_mv_condition, "explicit-git-authorization")
        self.assertEqual(authority.repository_state_mutation, "user-owned")

    def test_git_authority_parser_accepts_injected_malformed_policy_text(self) -> None:
        from model_check_git_authority import git_authority_from_text

        authority = git_authority_from_text(
            "Git operations are allowed.\nGit repository state is user-owned.\n"
        )

        self.assertEqual(authority.git_mv_condition, "missing-explicit-git-authorization")
        self.assertEqual(authority.repository_state_mutation, "user-owned")

    def test_orphan_common_rule_file_is_rejected(self) -> None:
        from model_check_routes import orphan_rule_findings

        findings = orphan_rule_findings(
            ROOT,
            self.model(),
            COMMON_AGENTS,
            extra_rule_paths=("model/RULES-ORPHAN.common.md",),
        )

        self.assertEqual([finding.code for finding in findings], ["orphan-model-artifact"])
        self.assertEqual(findings[0].path, "model/RULES-ORPHAN.common.md")
        self.assertEqual(findings[0].target, "route_graph")
        self.assertEqual(findings[0].severity, "error")

    def test_audience_header_is_machine_parseable(self) -> None:
        from model_check_routes import audience_header

        audience = audience_header(COMMON_AGENTS)

        self.assertEqual(audience.audience, "brain-local wrappers")
        self.assertEqual(audience.purpose, "shared operating guardrail")

    def test_startup_payload_decreases_from_frozen_task5_baseline_and_stays_under_cap(self) -> None:
        from model_check_context_baseline import canonical_context_baseline

        current = canonical_context_baseline(ROOT, self.model())
        frozen = json.loads(BASELINE.read_text(encoding="utf-8"))

        self.assertLess(
            current["budgets"]["startup"]["current_bytes"],
            frozen["budgets"]["startup"]["baseline_bytes"],
        )
        self.assertLessEqual(
            current["budgets"]["startup"]["current_bytes"],
            frozen["budgets"]["startup"]["cap_bytes"],
        )

    def test_frozen_context_baseline_matches_committed_digest(self) -> None:
        raw = BASELINE.read_bytes()
        digest_text = BASELINE_DIGEST.read_text("ascii")
        baseline = json.loads(raw)

        self.assertRegex(digest_text, r"^[0-9a-f]{64}\n$")
        self.assertEqual(hashlib.sha256(raw).hexdigest() + "\n", digest_text)
        self.assertEqual(baseline["schema_version"], "agent-brain-model-context-baseline/v1")


class OwnershipMutationCases(unittest.TestCase):
    def test_mutating_target_and_git_authority_changes_observable_contract(self) -> None:
        from model_check_git_authority import git_authority_from_text
        from model_check_routes import route_target_findings

        model = json.loads(MODEL.read_text(encoding="utf-8"))
        mutated = copy.deepcopy(model)
        mutated["route_graph"][0]["terminal"] = "model/RULES-MUTATED.common.md"
        common_text = COMMON_AGENTS.read_text(encoding="utf-8").replace(
            "Git operations require explicit user authorization.",
            "Git operations are allowed.",
        )
        with self.subTest("route-target"):
            findings = route_target_findings(ROOT, mutated, COMMON_AGENTS)
            self.assertEqual([finding.code for finding in findings], ["missing-route-target"])
        with self.subTest("git-authority"):
            self.assertEqual(
                git_authority_from_text(common_text).git_mv_condition,
                "missing-explicit-git-authorization",
            )


class Task7LedgerSemanticCases(unittest.TestCase):
    def fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        raw = tempfile.TemporaryDirectory()
        root = Path(raw.name)
        shutil.copy(ROOT / "AGENTS.md", root / "AGENTS.md")
        ledger = root / "docs" / "migrations" / "2026-07-operating-model-ledger.json"
        ledger.parent.mkdir(parents=True)
        shutil.copy(ROOT / "docs" / "migrations" / "2026-07-operating-model-ledger.json", ledger)
        return raw, root, ledger

    def findings_for(self, root: Path, ledger: Path) -> list[str]:
        from model_check_contract import CodeDef
        from model_check_ledger import task7_ledger_findings

        code = CodeDef(
            code="ledger-hash-mismatch",
            family="ledger",
            severity="error",
            selection="default",
            default=True,
            check="metadata-declared",
        )
        return [finding.code for finding in task7_ledger_findings(root, ledger, code)]

    def mutate_claim(self, ledger: Path, field: str, value: str | int) -> None:
        body = json.loads(ledger.read_text(encoding="utf-8"))
        trim_cluster = body["task7_trim_claims"][0]["cluster_id"]
        destination = next(
            claim["copied_destination"]
            for claim in body["relocation_claims"]
            if claim.get("cluster_id") == trim_cluster
        )
        destination[field] = value
        ledger.write_text(
            json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def mutate_trim_claim(self, ledger: Path, field: str, value: str | int) -> None:
        body = json.loads(ledger.read_text(encoding="utf-8"))
        body["task7_trim_claims"][0][field] = value
        ledger.write_text(
            json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def test_valid_current_task7_ledger_has_no_semantic_findings(self) -> None:
        raw, root, ledger = self.fixture()
        with raw:
            findings = self.findings_for(root, ledger)

        self.assertEqual(findings, [])

    def test_zero_destination_hash_is_rejected(self) -> None:
        raw, root, ledger = self.fixture()
        with raw:
            self.mutate_claim(ledger, "sha256", "0" * 64)
            findings = self.findings_for(root, ledger)

        self.assertEqual(findings, ["ledger-hash-mismatch"])

    def test_wrong_destination_path_or_range_is_rejected(self) -> None:
        raw, root, ledger = self.fixture()
        with raw:
            self.mutate_claim(ledger, "path", "MISSING.md")
            wrong_path = self.findings_for(root, ledger)
        raw, root, ledger = self.fixture()
        with raw:
            self.mutate_claim(ledger, "start_line", 9999)
            wrong_range = self.findings_for(root, ledger)

        self.assertEqual(wrong_path, ["ledger-hash-mismatch"])
        self.assertEqual(wrong_range, ["ledger-hash-mismatch"])

    def test_destination_byte_mutation_is_rejected(self) -> None:
        raw, root, ledger = self.fixture()
        with raw:
            agents = root / "AGENTS.md"
            agents.write_text(
                agents.read_text(encoding="utf-8").replace("## Rule triggers", "## Rule trigger drift"),
                encoding="utf-8",
            )
            findings = self.findings_for(root, ledger)

        self.assertEqual(findings, ["ledger-hash-mismatch"])

    def test_destination_byte_count_mismatch_is_rejected(self) -> None:
        raw, root, ledger = self.fixture()
        with raw:
            self.mutate_trim_claim(ledger, "removed_bytes", 0)
            findings = self.findings_for(root, ledger)

        self.assertEqual(findings, ["ledger-hash-mismatch"])


if __name__ == "__main__":
    unittest.main()

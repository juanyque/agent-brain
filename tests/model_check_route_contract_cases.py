from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, assert_never


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "model" / "SCRIPTS" / "model_check.py"
MODEL = ROOT / "model" / "OPERATING-MODEL.json"
RouteCode = Literal[
    "duplicate-route-id",
    "malformed-route-metadata",
    "missing-route-target",
    "orphan-model-artifact",
    "unmapped-cluster",
]
ROUTE_CODES: tuple[RouteCode, ...] = (
    "duplicate-route-id",
    "malformed-route-metadata",
    "missing-route-target",
    "orphan-model-artifact",
    "unmapped-cluster",
)


def _run_cli(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(CLI), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_model(path: Path, model: dict[str, object]) -> None:
    path.write_text(
        json.dumps(model, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _metadata_row(model: dict[str, object], code: RouteCode) -> dict[str, object]:
    contract = model["finding_contract"]
    if not isinstance(contract, dict):
        raise AssertionError("finding_contract fixture must be an object")
    rows = contract["code_metadata"]
    if not isinstance(rows, list):
        raise AssertionError("code_metadata fixture must be a list")
    return next(row for row in rows if isinstance(row, dict) and row.get("code") == code)


def _severity_defaults(model: dict[str, object]) -> dict[str, object]:
    contract = model["finding_contract"]
    if not isinstance(contract, dict):
        raise AssertionError("finding_contract fixture must be an object")
    defaults = contract["severity_defaults"]
    if not isinstance(defaults, dict):
        raise AssertionError("severity_defaults fixture must be an object")
    return defaults


def _induce_route_defect(root: Path, model: dict[str, object], code: RouteCode) -> None:
    routes = model["route_graph"]
    if not isinstance(routes, list):
        raise AssertionError("route_graph fixture must be a list")
    match code:
        case "duplicate-route-id":
            routes.append(routes[0])
        case "malformed-route-metadata":
            routes.append({"route_id": "rule.malformed"})
        case "missing-route-target":
            daily = next(row for row in routes if row["route_id"] == "rule.daily-notes")
            daily["terminal"] = "model/RULES-MISSING.common.md"
        case "orphan-model-artifact":
            (root / "model" / "RULES-ORPHAN.common.md").write_text(
                "# Orphan\n",
                encoding="utf-8",
            )
        case "unmapped-cluster":
            attachments = next(row for row in routes if row["route_id"] == "rule.attachments")
            attachments["terminal"] = "model/RULES-MISSING-ATTACHMENT.common.md"
        case unreachable:
            assert_never(unreachable)


def _run_route_defect(
    code: RouteCode,
    *,
    selector: tuple[str, ...] = (),
    warning: bool = False,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        shutil.copytree(ROOT / "model", root / "model")
        shutil.copytree(ROOT / "skills", root / "skills")
        shutil.copytree(ROOT / "docs", root / "docs")
        shutil.copy2(ROOT / "AGENTS.md", root / "AGENTS.md")
        model_path = root / "model" / "OPERATING-MODEL.json"
        model = json.loads(model_path.read_text(encoding="utf-8"))
        if warning:
            _metadata_row(model, code)["severity"] = "warning"
            _severity_defaults(model)[code] = "warning"
        _induce_route_defect(root, model, code)
        _write_model(model_path, model)
        return _run_cli(
            "--root",
            str(root),
            "--model",
            str(model_path),
            "--strict",
            *selector,
            "--format",
            "json",
        )


class RouteContractCases:
    def test_route_family_must_be_selected_by_default(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        model["finding_contract"]["defaults"].remove("route-target")
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "OPERATING-MODEL.json"
            _write_model(path, model)
            result = _run_cli("--model", str(path), "--strict", "--format", "json")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("route-target must be selected by default", result.stderr)

    def test_required_route_codes_must_be_default_enabled(self) -> None:
        for code in ROUTE_CODES:
            with self.subTest(code=code):
                model = json.loads(MODEL.read_text(encoding="utf-8"))
                _metadata_row(model, code)["default"] = False
                with tempfile.TemporaryDirectory() as raw:
                    path = Path(raw) / "OPERATING-MODEL.json"
                    _write_model(path, model)
                    result = _run_cli(
                        "--model",
                        str(path),
                        "--strict",
                        "--only",
                        "route-target",
                        "--format",
                        "json",
                    )

                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn(code, result.stderr)

    def test_required_route_severity_declarations_must_match(self) -> None:
        for code in ROUTE_CODES:
            for mutated_side in ("code_metadata", "severity_defaults"):
                with self.subTest(code=code, mutated_side=mutated_side):
                    model = json.loads(MODEL.read_text(encoding="utf-8"))
                    if mutated_side == "code_metadata":
                        _metadata_row(model, code)["severity"] = "warning"
                    else:
                        _severity_defaults(model)[code] = "warning"
                    with tempfile.TemporaryDirectory() as raw:
                        path = Path(raw) / "OPERATING-MODEL.json"
                        _write_model(path, model)
                        result = _run_cli(
                            "--model",
                            str(path),
                            "--strict",
                            "--only",
                            "route-target",
                            "--format",
                            "json",
                        )

                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertIn(code, result.stderr)

    def test_all_route_outcomes_are_enabled_in_default_strict_mode(self) -> None:
        for code in ROUTE_CODES:
            for selector in ((), ("--only", "route-target")):
                with self.subTest(code=code, selector=selector):
                    result = _run_route_defect(code, selector=selector)
                    findings = json.loads(result.stdout)["findings"]
                    route_findings = [
                        (finding["code"], finding["severity"])
                        for finding in findings
                        if finding["code"] == code
                    ]

                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, "")
                    self.assertTrue(route_findings)
                    self.assertEqual(set(route_findings), {(code, "error")})

    def test_coupled_route_warning_metadata_controls_strict_cli(self) -> None:
        for code in ROUTE_CODES:
            with self.subTest(code=code):
                result = _run_route_defect(
                    code,
                    selector=("--only", code),
                    warning=True,
                )
                findings = json.loads(result.stdout)["findings"]

                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "")
                self.assertTrue(findings)
                self.assertEqual(
                    {(finding["code"], finding["severity"]) for finding in findings},
                    {(code, "warning")},
                )

    def test_route_code_metadata_omission_is_rejected_by_strict_cli(self) -> None:
        omitted_sets = tuple({code} for code in ROUTE_CODES) + (set(ROUTE_CODES),)
        for omitted in omitted_sets:
            for selector in (
                (),
                ("--only", "route-target"),
                ("--only", sorted(omitted)[0]),
            ):
                with self.subTest(omitted=sorted(omitted), selector=selector):
                    model = json.loads(MODEL.read_text(encoding="utf-8"))
                    contract = model["finding_contract"]
                    contract["code_metadata"] = [
                        row
                        for row in contract["code_metadata"]
                        if row["code"] not in omitted
                    ]
                    route_family = next(
                        row
                        for row in contract["families"]
                        if row["family"] == "route-target"
                    )
                    route_family["codes"] = [
                        code for code in route_family["codes"] if code not in omitted
                    ]
                    for code in omitted:
                        del contract["severity_defaults"][code]
                    with tempfile.TemporaryDirectory() as raw:
                        path = Path(raw) / "OPERATING-MODEL.json"
                        _write_model(path, model)
                        result = _run_cli(
                            "--model",
                            str(path),
                            "--strict",
                            *selector,
                            "--format",
                            "json",
                        )

                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertIn(", ".join(sorted(omitted)), result.stderr)

    def test_required_route_code_reclassification_is_rejected_by_strict_cli(self) -> None:
        for code in ROUTE_CODES:
            for selector in ((), ("--only", "route-target")):
                with self.subTest(code=code, selector=selector):
                    model = json.loads(MODEL.read_text(encoding="utf-8"))
                    _metadata_row(model, code)["family"] = "audience"
                    with tempfile.TemporaryDirectory() as raw:
                        path = Path(raw) / "OPERATING-MODEL.json"
                        _write_model(path, model)
                        result = _run_cli(
                            "--model",
                            str(path),
                            "--strict",
                            *selector,
                            "--format",
                            "json",
                        )

                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertIn(code, result.stderr)

    def test_unknown_family_selection_is_rejected_at_metadata_boundary(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        contract = model["finding_contract"]
        route_family = next(
            row for row in contract["families"] if row["family"] == "route-target"
        )
        route_family["selection"] = "disabled"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model_path = root / "OPERATING-MODEL.json"
            _induce_route_defect(root, model, "missing-route-target")
            _write_model(model_path, model)
            result = _run_cli(
                "--root",
                str(ROOT),
                "--model",
                str(model_path),
                "--strict",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("unknown family selection", result.stderr)

    def test_duplicate_family_metadata_is_rejected_at_metadata_boundary(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        contract = model["finding_contract"]
        route_family = next(
            row for row in contract["families"] if row["family"] == "route-target"
        )
        contract["families"].append(dict(route_family))
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "OPERATING-MODEL.json"
            _write_model(path, model)
            result = _run_cli("--model", str(path), "--strict", "--format", "json")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("duplicate family metadata", result.stderr)

    def test_duplicate_code_metadata_is_rejected_before_it_can_downgrade_severity(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        contract = model["finding_contract"]
        warning_row = dict(_metadata_row(model, "missing-route-target"))
        warning_row["severity"] = "warning"
        contract["code_metadata"].append(warning_row)
        _severity_defaults(model)["missing-route-target"] = "warning"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model_path = root / "OPERATING-MODEL.json"
            _induce_route_defect(root, model, "missing-route-target")
            _write_model(model_path, model)
            result = _run_cli(
                "--root",
                str(ROOT),
                "--model",
                str(model_path),
                "--strict",
                "--only",
                "missing-route-target",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("duplicate code metadata", result.stderr)

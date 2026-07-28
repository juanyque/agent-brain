#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "model" / "SCRIPTS"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from model_check_context_validator import validate_context_baseline  # noqa: E402


Mutation = Callable[[dict[str, object]], None]


def _load_baseline() -> dict[str, object]:
    return json.loads((ROOT / "tests" / "fixtures" / "model-context-baseline.json").read_text())


def _raw(value: dict[str, object], final_lf: str = "\n") -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + final_lf
    ).encode("utf-8")


def _segment(value: dict[str, object], scenario_index: int, segment_index: int) -> dict[str, object]:
    return value["scenarios"][scenario_index]["segments"][segment_index]


def scenario_ordering(value: dict[str, object]) -> None:
    value["scenarios"] = list(reversed(value["scenarios"]))


def absolute_path(value: dict[str, object]) -> None:
    _segment(value, 0, 0)["path"] = "/tmp/body.md"


def backslash_path(value: dict[str, object]) -> None:
    _segment(value, 0, 0)["path"] = "model\\BRAIN.common.md"


def content_hash(value: dict[str, object]) -> None:
    _segment(value, 0, 0)["sha256"] = "0" * 64


def duplicate_scenario(value: dict[str, object]) -> None:
    value["scenarios"][1]["id"] = value["scenarios"][0]["id"]


def missing_scenario(value: dict[str, object]) -> None:
    value["scenarios"].pop()


def duplicate_terminal(value: dict[str, object]) -> None:
    value["scenarios"][1]["terminal"] = value["scenarios"][0]["terminal"]


def missing_terminal(value: dict[str, object]) -> None:
    value["scenarios"][0]["terminal"] = "model/MISSING.common.md"


def duplicate_ordinal(value: dict[str, object]) -> None:
    _segment(value, 0, 1)["ordinal"] = 0


def missing_ordinal(value: dict[str, object]) -> None:
    _segment(value, 0, 1)["ordinal"] = 4


def duplicate_agents(value: dict[str, object]) -> None:
    value["budgets"]["startup"]["segments"].append(
        dict(value["budgets"]["startup"]["segments"][0])
    )


def brain_injection(value: dict[str, object]) -> None:
    injected = dict(value["budgets"]["startup"]["segments"][0])
    injected["path"] = "model/BRAIN.common.md"
    value["budgets"]["startup"]["segments"].append(injected)


def terminal_injection(value: dict[str, object]) -> None:
    value["scenarios"][0]["terminal_load_count"] = 2


def broad_body(value: dict[str, object]) -> None:
    injected = dict(_segment(value, 0, 0))
    injected["ordinal"] = len(value["scenarios"][1]["segments"])
    value["scenarios"][1]["segments"].append(injected)


def startup_over(value: dict[str, object]) -> None:
    value["budgets"]["startup"]["current_bytes"] = (
        value["budgets"]["startup"]["cap_bytes"] + 1
    )


def conditional_over(value: dict[str, object]) -> None:
    scenario_id = sorted(value["budgets"]["conditional_scenarios"])[0]
    budget = value["budgets"]["conditional_scenarios"][scenario_id]
    budget["current_bytes"] = budget["cap_bytes"] + 1


CASES: dict[str, tuple[str, str, Mutation, str]] = {
    "scenario-ordering": ("scenario-order", "$.scenarios", scenario_ordering, "\n"),
    "absolute-path": ("segment-path", "$.scenarios[scenario.attachments].segments[0].path", absolute_path, "\n"),
    "backslash-path": ("segment-path", "$.scenarios[scenario.attachments].segments[0].path", backslash_path, "\n"),
    "missing-final-lf": ("baseline-final-lf", "$", lambda value: None, ""),
    "excess-final-lf": ("baseline-final-lf", "$", lambda value: None, "\n\n"),
    "content-hash": ("segment-sha256", "$.scenarios[scenario.attachments].segments[0].sha256", content_hash, "\n"),
    "digest-mismatch": ("digest-mismatch", "tests/fixtures/model-context-baseline.sha256", lambda value: None, "\n"),
    "duplicate-scenario": ("scenario-set", "$.scenarios", duplicate_scenario, "\n"),
    "missing-scenario": ("scenario-set", "$.scenarios", missing_scenario, "\n"),
    "duplicate-terminal": ("terminal-set", "$.scenarios", duplicate_terminal, "\n"),
    "missing-terminal": ("terminal-set", "$.scenarios", missing_terminal, "\n"),
    "duplicate-ordinal": ("segment-ordinal", "$.scenarios[scenario.attachments].segments", duplicate_ordinal, "\n"),
    "missing-ordinal": ("segment-ordinal", "$.scenarios[scenario.attachments].segments", missing_ordinal, "\n"),
    "duplicate-agents": ("runtime-agents-count", "$.budgets.startup.segments", duplicate_agents, "\n"),
    "brain-injection": ("brain-eager", "$.budgets.startup.segments", brain_injection, "\n"),
    "terminal-injection": ("terminal-load-count", "$.scenarios[scenario.attachments].terminal_load_count", terminal_injection, "\n"),
    "broad-body": ("broad-body-inclusion", "$.scenarios[scenario.constraints].segments", broad_body, "\n"),
    "startup-over": ("startup-budget", "$.budgets.startup.current_bytes", startup_over, "\n"),
    "conditional-over": ("conditional-budget", "$.budgets.conditional_scenarios.scenario.attachments", conditional_over, "\n"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, choices=sorted(CASES))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    code, path, mutate, final_lf = CASES[args.case]
    model = json.loads((ROOT / "model" / "OPERATING-MODEL.json").read_text())
    baseline = _load_baseline()
    mutate(baseline)
    raw = _raw(baseline, final_lf)
    digest = hashlib.sha256(raw).hexdigest() + "\n"
    if args.case == "digest-mismatch":
        digest = "0" * 64 + "\n"
    findings = validate_context_baseline(ROOT, model, raw, digest.encode("ascii"))
    pairs = {(finding.code, finding.path) for finding in findings}
    ok = (code, path) in pairs
    print(
        json.dumps(
            {
                "case": args.case,
                "expected": {"code": code, "path": path},
                "findings": [
                    {"code": finding.code, "message": finding.message, "path": finding.path}
                    for finding in findings
                ],
                "input_sha256": hashlib.sha256(raw).hexdigest(),
                "ok": ok,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

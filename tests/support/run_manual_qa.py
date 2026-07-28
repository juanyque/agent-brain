#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from evidence_json import JsonValue, file_record, load_json, read_bytes_no_follow
from evidence_runs import run_lane
from evidence_seals import lane_record


class ManualQaError(Exception):
    pass


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    for name in (
        "--frozen-manifest", "--freeze-before", "--freeze-after", "--runs",
        "--qa-root", "--connected-brain", "--artifact", "--artifact-manifest",
        "--lane-output",
    ):
        parser.add_argument(name, type=Path, required=True)
    return parser.parse_args()


def run(command: list[str], cwd: Path, log_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "GIT_OPTIONAL_LOCKS": "0",
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if log_dir is not None:
        env["AGENT_BRAIN_LOG_DIR"] = str(log_dir)
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
    )


def require(result: subprocess.CompletedProcess[str], label: str) -> None:
    if result.returncode != 0:
        raise ManualQaError(f"{label} failed: {result.stderr}")


def require_status(status: int, label: str) -> None:
    if status != 0:
        raise ManualQaError(f"{label} failed with status {status}")


def run_f3_step(step: int, cwd: Path, freeze: Path, evidence_root: Path, command: list[str]) -> None:
    status = run_lane(
        "F3",
        step,
        cwd,
        freeze,
        evidence_root,
        command,
        None,
    )
    require_status(status, f"F3 step {step}")


def run_statuses(runs: Path) -> list[JsonValue]:
    paths = sorted(runs.glob("*.json"), key=lambda path: int(path.stem))
    return [load_json(path).get("exit_status") for path in paths]


def main() -> int:
    parsed = arguments()
    helper = Path(__file__).with_name("evidence_contract.py")
    evidence_root = parsed.frozen_manifest.parent
    if parsed.runs != evidence_root / "F3-runs":
        raise ManualQaError("F3 --runs must be the evidence-root F3-runs directory")
    before = run(
        [
            sys.executable, str(helper), "verify-freeze",
            "--freeze", str(parsed.frozen_manifest),
            "--evidence-root", str(evidence_root),
            "--impl-root", str(Path.cwd()),
            "--recompute", str(parsed.freeze_before),
        ],
        Path.cwd(),
    )
    require(before, "initial freeze verification")
    frozen = json.loads(parsed.frozen_manifest.read_text("utf-8"))
    implementation = frozen.get("implementation")
    if not isinstance(implementation, dict):
        raise ManualQaError("freeze lacks materializable implementation")
    manifest = evidence_root / implementation["manifest"]
    archive = evidence_root / implementation["archive"]
    if parsed.qa_root.exists() or parsed.qa_root.is_symlink():
        if parsed.qa_root.is_symlink() or not parsed.qa_root.is_dir() or any(parsed.qa_root.iterdir()):
            raise ManualQaError("qa root must be an empty real directory")
    else:
        parsed.qa_root.mkdir(parents=True, exist_ok=False)
    destination = parsed.qa_root / "implementation"
    outputs = parsed.qa_root / "outputs"
    outputs.mkdir()
    materialized = run(
        [
            sys.executable, str(helper), "materialize",
            "--manifest", str(manifest), "--archive", str(archive),
            "--output", str(destination),
        ],
        Path.cwd(),
    )
    require(materialized, "implementation materialization")
    temp_brain = parsed.qa_root / "brain"
    temp_brain.mkdir()
    connected_before = outputs / "connected-brain-before.json"
    connected_before_sidecars = outputs / "connected-brain-before-sidecars"
    connected_after = outputs / "connected-brain-after.json"
    connected_after_sidecars = outputs / "connected-brain-after-sidecars"
    run_f3_step(
        1,
        destination,
        parsed.frozen_manifest,
        evidence_root,
        [
            sys.executable, str(helper), "capture-state",
            "--kind", "brain",
            "--root", str(parsed.connected_brain),
            "--output", str(connected_before),
            "--sidecar-dir", str(connected_before_sidecars),
        ],
    )
    run_f3_step(
        2,
        destination,
        parsed.frozen_manifest,
        evidence_root,
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
    )
    run_f3_step(
        3,
        destination,
        parsed.frozen_manifest,
        evidence_root,
        [
            "/usr/bin/env",
            f"AGENT_BRAIN_LOG_DIR={outputs}",
            sys.executable,
            "model/SCRIPTS/home_setup.py",
            "--brain",
            str(temp_brain),
        ],
    )
    run_f3_step(
        4,
        destination,
        parsed.frozen_manifest,
        evidence_root,
        [
            sys.executable,
            "model/SCRIPTS/model_check.py",
            "--brain",
            str(parsed.connected_brain),
            "--format",
            "json",
        ],
    )
    run_f3_step(
        5,
        destination,
        parsed.frozen_manifest,
        evidence_root,
        [
            sys.executable, str(helper), "capture-state",
            "--kind", "brain",
            "--root", str(parsed.connected_brain),
            "--output", str(connected_after),
            "--sidecar-dir", str(connected_after_sidecars),
        ],
    )
    run_f3_step(
        6,
        destination,
        parsed.frozen_manifest,
        evidence_root,
        [
            sys.executable, str(helper), "compare-state",
            "--left", str(connected_before),
            "--left-sidecars", str(connected_before_sidecars),
            "--right", str(connected_after),
            "--right-sidecars", str(connected_after_sidecars),
        ],
    )
    run_f3_step(
        7,
        destination,
        parsed.frozen_manifest,
        evidence_root,
        [
            sys.executable, str(helper), "capture-worktree",
            "--root", str(parsed.qa_root),
            "--root-name", "qa",
            "--archive", str(parsed.artifact),
            "--manifest", str(parsed.artifact_manifest),
        ],
    )
    after = run(
        [
            sys.executable, str(helper), "verify-freeze",
            "--freeze", str(parsed.frozen_manifest),
            "--evidence-root", str(evidence_root),
            "--impl-root", str(destination),
            "--recompute", str(parsed.freeze_after),
        ],
        destination,
    )
    require(after, "final freeze verification")
    frozen_equal = read_bytes_no_follow(parsed.freeze_before) == read_bytes_no_follow(parsed.freeze_after)
    if not frozen_equal:
        raise ManualQaError("frozen closure changed during manual QA")
    statuses = run_statuses(parsed.runs)
    connected_brain_equal = all(status == 0 for status in statuses[0:1] + statuses[3:6])
    temp_brain_equal = statuses[2] == 0
    verdict = {
        "checker": statuses[3],
        "connected_brain_equal": connected_brain_equal,
        "frozen_equal": frozen_equal,
        "setup": statuses[2],
        "source_equal": before.returncode == 0 and after.returncode == 0,
        "temp_brain_equal": temp_brain_equal,
        "tests": statuses[1],
        "verdict": "APPROVE",
    }
    lane_record(
        "F3",
        parsed.frozen_manifest,
        parsed.runs,
        parsed.freeze_before,
        parsed.freeze_after,
        parsed.lane_output,
        {
            "artifact": file_record("evidence", evidence_root, parsed.artifact),
            "artifact_manifest": file_record("evidence", evidence_root, parsed.artifact_manifest),
            "command_statuses": statuses,
            "manual_qa": verdict,
            "parity": {
                "connected_brain_equal": connected_brain_equal,
                "frozen_equal": frozen_equal,
                "source_equal": before.returncode == 0 and after.returncode == 0,
                "temp_brain_equal": temp_brain_equal,
            },
        },
    )
    print(json.dumps(verdict, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ManualQaError, OSError, KeyError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from None

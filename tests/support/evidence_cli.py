from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import assert_never

from evidence_closure import create_wave_closure, verify_wave_closure
from evidence_closure_records import pin_json
from evidence_json import ContractError, canonical_bytes, read_bytes_no_follow, validate_manifest
from evidence_ledger import create_ledger_checkpoint, verify_ledger_checkpoint
from evidence_model import validate_schema
from evidence_review import create_plan_review, create_successor_plan_review, verify_plan_review
from evidence_runs import run_lane, run_todo
from evidence_seals import (
    approve,
    final_approve,
    final_review,
    finalize,
    freeze,
    freeze_context,
    lane_record,
    seal_todo,
    verify_completion,
    verify_freeze,
    verify_todo,
)
from evidence_wave import immutable_states, verify_wave, wave
from evidence_state import capture_state, compare_state
from evidence_tree import capture_worktree, materialize, verify_materialized


def _path(parser: argparse.ArgumentParser, name: str, required: bool = True) -> None:
    parser.add_argument(name, type=Path, required=required)


def build_parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)
    verify_json = commands.add_parser("verify-json")
    _path(verify_json, "--input")
    worktree = commands.add_parser("capture-worktree")
    for name in ("--root", "--archive", "--manifest"):
        _path(worktree, name)
    worktree.add_argument("--root-name", default="implementation")
    restore = commands.add_parser("materialize")
    for name in ("--manifest", "--archive", "--output"):
        _path(restore, name)
    verify_restore = commands.add_parser("verify-materialized")
    _path(verify_restore, "--manifest")
    _path(verify_restore, "--root")
    state = commands.add_parser("capture-state")
    state.add_argument("--kind", choices=("source", "brain"), required=True)
    for name in ("--root", "--output", "--sidecar-dir"):
        _path(state, name)
    compare = commands.add_parser("compare-state")
    for name in ("--left", "--left-sidecars", "--right", "--right-sidecars"):
        _path(compare, name)
    review = commands.add_parser("plan-review")
    for name in ("--plan", "--draft", "--momus-receipt", "--independent-receipt", "--output"):
        _path(review, name)
    successor_review = commands.add_parser("successor-plan-review")
    for name in (
        "--plan", "--impl-root", "--draft", "--brain-root", "--prior-seal",
        "--evidence-root", "--momus-receipt", "--independent-receipt", "--output",
    ):
        _path(successor_review, name)
    verify_review = commands.add_parser("verify-plan-review")
    for name in ("--seal", "--evidence-root"):
        _path(verify_review, name)
    _path(verify_review, "--brain-root", required=False)
    _path(verify_review, "--implementation-root", required=False)
    run_todo_parser = commands.add_parser("run-todo")
    run_todo_parser.add_argument("--todo", type=int, required=True)
    run_todo_parser.add_argument("--step", type=int, required=True)
    _path(run_todo_parser, "--cwd")
    _path(run_todo_parser, "--evidence-root")
    run_todo_parser.add_argument("--shell")
    run_todo_parser.add_argument("argv", nargs=argparse.REMAINDER)
    seal = commands.add_parser("seal-todo")
    seal.add_argument("--todo", type=int, required=True)
    seal.add_argument("--baseline-commit", required=True)
    for name in (
        "--plan", "--impl-root", "--source-baseline", "--brain-baseline",
        "--runs", "--task-log", "--output",
    ):
        _path(seal, name)
    _path(seal, "--implementation-manifest", required=False)
    _path(seal, "--implementation-archive", required=False)
    verify_todo_parser = commands.add_parser("verify-todo")
    _path(verify_todo_parser, "--receipt")
    _path(verify_todo_parser, "--evidence-root")
    closure = commands.add_parser("create-closure-v2")
    closure.add_argument("--wave", type=int, required=True)
    for name in ("--plan", "--impl-root", "--implementation-manifest", "--implementation-archive", "--output"):
        _path(closure, name)
    for name in ("--draft", "--review-seal", "--tooling-review", "--independent-gate"):
        _path(closure, name, required=False)
    closure.add_argument("--task-receipt", nargs=3, action="append", metavar=("TODO", "PATH", "EVIDENCE_ROOT"))
    closure.add_argument("--governed-run", nargs=3, action="append", metavar=("TODO", "PATH", "EVIDENCE_ROOT"))
    closure.add_argument("--superseded-receipt", nargs=3, action="append", metavar=("TODO", "PATH", "EVIDENCE_ROOT"))
    closure.add_argument("--source-before", nargs=2, required=True, metavar=("STATE", "SIDECARS"))
    closure.add_argument("--source-after", nargs=2, required=True, metavar=("STATE", "SIDECARS"))
    closure.add_argument("--brain-before", nargs=2, required=True, metavar=("STATE", "SIDECARS"))
    closure.add_argument("--brain-after", nargs=2, required=True, metavar=("STATE", "SIDECARS"))
    closure.add_argument("--report", action="append")
    closure.add_argument("--cleanup", action="append")
    verify_closure = commands.add_parser("verify-closure-v2")
    _path(verify_closure, "--receipt")
    wave_parser = commands.add_parser("wave")
    wave_parser.add_argument("--wave", type=int, required=True)
    for name in (
        "--plan", "--draft", "--review-seal", "--source-baseline",
        "--brain-baseline", "--impl-root", "--evidence-root", "--output",
    ):
        _path(wave_parser, name)
    approve_parser = commands.add_parser("approve-wave")
    approve_parser.add_argument("--wave", type=int, required=True)
    for name in ("--receipt", "--message", "--output"):
        _path(approve_parser, name)
    _path(approve_parser, "--impl-root", required=False)
    _path(approve_parser, "--evidence-root", required=False)
    _path(approve_parser, "--prior-ledger-checkpoint", required=False)
    verify_wave_parser = commands.add_parser("verify-wave")
    verify_wave_parser.add_argument("--wave", type=int, required=True)
    _path(verify_wave_parser, "--evidence-root")
    freeze_parser = commands.add_parser("freeze")
    for name in ("--plan", "--draft", "--review-seal", "--impl-root", "--evidence-root", "--output"):
        _path(freeze_parser, name)
    _path(freeze_parser, "--prior-ledger-checkpoint", required=False)
    verify_freeze_parser = commands.add_parser("verify-freeze")
    _path(verify_freeze_parser, "--freeze")
    _path(verify_freeze_parser, "--impl-root")
    _path(verify_freeze_parser, "--recompute", required=False)
    _path(verify_freeze_parser, "--evidence-root", required=False)
    checkpoint = commands.add_parser("ledger-checkpoint")
    for name in ("--impl-root", "--evidence-root", "--output", "--bytes-output"):
        _path(checkpoint, name)
    _path(checkpoint, "--prior-checkpoint", required=False)
    verify_checkpoint = commands.add_parser("verify-ledger-checkpoint")
    _path(verify_checkpoint, "--checkpoint")
    _path(verify_checkpoint, "--evidence-root")
    lane_run = commands.add_parser("run-lane")
    lane_run.add_argument("--lane", required=True)
    lane_run.add_argument("--step", type=int, required=True)
    for name in ("--cwd", "--freeze", "--evidence-root"):
        _path(lane_run, name)
    lane_run.add_argument("--shell")
    lane_run.add_argument("argv", nargs=argparse.REMAINDER)
    lane = commands.add_parser("lane")
    lane.add_argument("--lane", required=True)
    for name in ("--freeze", "--runs", "--before", "--after", "--output"):
        _path(lane, name)
    context = commands.add_parser("freeze-context")
    for name in ("--source", "--digest", "--output", "--output-digest"):
        _path(context, name)
    review_final = commands.add_parser("final-review")
    _path(review_final, "--freeze")
    review_final.add_argument("--lanes", nargs="+", type=Path, required=True)
    _path(review_final, "--output")
    _path(review_final, "--impl-root", required=False)
    _path(review_final, "--evidence-root", required=False)
    _path(review_final, "--prior-ledger-checkpoint", required=False)
    approve_final = commands.add_parser("final-approve")
    for name in ("--review", "--message", "--output"):
        _path(approve_final, name)
    finalize_parser = commands.add_parser("finalize")
    for name in ("--review", "--approval", "--evidence-root", "--output"):
        _path(finalize_parser, name)
    _path(finalize_parser, "--impl-root", required=False)
    _path(finalize_parser, "--prior-ledger-checkpoint", required=False)
    verify = commands.add_parser("verify")
    _path(verify, "--completion", required=False)
    _path(verify, "--freeze", required=False)
    _path(verify, "--impl-root", required=False)
    _path(verify, "--evidence-root", required=False)
    verify.add_argument("--require-source-preflight", action="store_true")
    verify.add_argument("--require-brain-equality", action="store_true")
    verify.add_argument("--require-wave-approvals", action="store_true")
    _path(verify, "--status", required=False)
    return result


def _actual_argv(arguments: argparse.Namespace) -> list[str] | None:
    values = list(arguments.argv)
    if values and values[0] == "--":
        values.pop(0)
    return values or None


def execute(a: argparse.Namespace) -> int:
    match a.command:
        case "verify-json":
            pinned = pin_json(a.input)
            if pinned.data != canonical_bytes(pinned.value):
                raise ContractError("JSON is not canonical")
            validate_manifest(pinned.value)
            validate_schema(pinned.value)
        case "capture-worktree":
            capture_worktree(a.root, a.archive, a.manifest, a.root_name)
        case "materialize":
            materialize(a.manifest, a.archive, a.output)
        case "verify-materialized":
            verify_materialized(a.manifest, a.root)
        case "capture-state":
            capture_state(a.kind, a.root, a.output, a.sidecar_dir)
        case "compare-state":
            return 0 if compare_state(a.left, a.left_sidecars, a.right, a.right_sidecars) else 1
        case "plan-review":
            create_plan_review(a.plan, a.draft, a.momus_receipt, a.independent_receipt, a.output)
        case "successor-plan-review":
            create_successor_plan_review(
                a.plan,
                a.impl_root,
                a.draft,
                a.brain_root,
                a.prior_seal,
                a.evidence_root,
                a.momus_receipt,
                a.independent_receipt,
                a.output,
            )
        case "verify-plan-review":
            verify_plan_review(a.seal, a.evidence_root, a.brain_root, a.implementation_root)
        case "run-todo":
            return run_todo(a.todo, a.step, a.cwd, a.evidence_root, _actual_argv(a), a.shell)
        case "seal-todo":
            seal_todo(a.todo, a.plan, a.baseline_commit, a.impl_root, a.source_baseline,
                      a.brain_baseline, a.runs, a.task_log, a.output,
                      a.implementation_manifest, a.implementation_archive)
        case "verify-todo":
            verify_todo(a.receipt, a.evidence_root)
        case "create-closure-v2":
            create_wave_closure(a)
        case "verify-closure-v2":
            verify_wave_closure(a.receipt)
        case "wave":
            wave(
                a.wave,
                a.plan,
                a.draft,
                a.review_seal,
                a.source_baseline,
                a.brain_baseline,
                a.impl_root,
                a.evidence_root,
                a.output,
            )
        case "approve-wave":
            approve(
                "wave",
                str(a.wave),
                a.receipt,
                a.message,
                a.output,
                a.impl_root,
                a.evidence_root,
                a.prior_ledger_checkpoint,
            )
        case "verify-wave":
            verify_wave(a.wave, a.evidence_root)
        case "freeze":
            freeze(a.plan, a.draft, a.review_seal, a.impl_root, a.evidence_root, a.output, a.prior_ledger_checkpoint)
        case "verify-freeze":
            verify_freeze(a.freeze, a.evidence_root or a.freeze.parent, a.recompute, a.impl_root)
        case "ledger-checkpoint":
            create_ledger_checkpoint(a.impl_root, a.evidence_root, a.output, a.bytes_output, a.prior_checkpoint)
        case "verify-ledger-checkpoint":
            verify_ledger_checkpoint(a.checkpoint, a.evidence_root)
        case "run-lane":
            return run_lane(a.lane, a.step, a.cwd, a.freeze, a.evidence_root,
                            _actual_argv(a), a.shell)
        case "lane":
            lane_record(a.lane, a.freeze, a.runs, a.before, a.after, a.output)
        case "freeze-context":
            freeze_context(a.source, a.digest, a.output, a.output_digest)
        case "final-review":
            final_review(a.freeze, a.lanes, a.output, a.impl_root, a.evidence_root, a.prior_ledger_checkpoint)
        case "final-approve":
            final_approve(a.review, a.message, a.output)
        case "finalize":
            finalize(a.review, a.approval, a.evidence_root, a.output, a.impl_root, a.prior_ledger_checkpoint)
        case "verify":
            if a.completion is not None:
                verify_completion(a.completion, a.evidence_root or a.completion.parent)
            elif a.freeze is not None:
                if a.impl_root is None:
                    raise ContractError("verify-freeze requires --impl-root")
                evidence_root = a.evidence_root or a.freeze.parent
                verify_freeze(a.freeze, evidence_root, None, a.impl_root)
                if a.require_wave_approvals or a.require_source_preflight or a.require_brain_equality:
                    wave_receipt = verify_wave(4, evidence_root, a.impl_root)
                    if a.require_source_preflight or a.require_brain_equality:
                        source_state, brain_state = immutable_states(wave_receipt)
                        if a.require_source_preflight and not isinstance(source_state, dict):
                            raise ContractError("required lifecycle source binding is missing")
                        if a.require_brain_equality and not isinstance(brain_state, dict):
                            raise ContractError("required lifecycle brain binding is missing")
                if a.status is not None:
                    read_bytes_no_follow(a.status)
            else:
                raise ContractError("verify requires --completion or --freeze")
        case unknown:
            assert_never(unknown)
    return 0


def main() -> int:
    try:
        return execute(build_parser().parse_args())
    except ContractError as error:
        print(str(error), file=sys.stderr)
        return 2
    except (KeyError, OSError, TypeError, ValueError) as error:
        print(f"contract boundary error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

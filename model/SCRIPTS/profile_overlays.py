#!/usr/bin/env python3
"""Project selected profile resources into explicit runtime target roots.

The projector is intentionally runtime-neutral. Runtime adapters provide one target
root per resource kind, while the private profile supplies brain-relative sources
and target-root-relative destinations. Dry-run is the default.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from _common import Reporter, build_command_string
from environment_profiles import ProfileError, ResolvedProfile, resolve_profile


QUARANTINE_DIR = Path("INBOX/_PROFILE_OVERLAYS")
OVERLAY_KINDS = {"rule", "skill", "agent", "theme"}


@dataclass(frozen=True)
class OverlayPlan:
    runtime: str
    kind: str
    source: Path
    target: Path
    quarantine: Path
    action: str


def parse_target_roots(values: Sequence[str]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for value in values:
        kind, separator, raw_root = value.partition("=")
        if not separator or kind not in OVERLAY_KINDS or not raw_root:
            expected = ", ".join(sorted(OVERLAY_KINDS))
            raise ProfileError(
                f"invalid --target-root {value!r}; expected KIND=PATH where KIND is {expected}"
            )
        if kind in roots:
            raise ProfileError(f"duplicate --target-root for {kind!r}")
        roots[kind] = Path(raw_root).expanduser()
    return roots


def _relative_target(raw: str) -> Path:
    target = Path(raw)
    if target.is_absolute() or ".." in target.parts or target == Path("."):
        raise ProfileError(f"overlay target must be relative: {raw!r}")
    return target


def _assert_parent_within_root(target: Path, root: Path) -> None:
    resolved_root = root.resolve(strict=False)
    resolved_parent = target.parent.resolve(strict=False)
    try:
        resolved_parent.relative_to(resolved_root)
    except ValueError as exc:
        raise ProfileError(
            f"overlay target parent escapes its configured root: {target}"
        ) from exc


def build_overlay_plan(
    brain_root: Path,
    resolved: ResolvedProfile,
    *,
    runtime: str,
    target_roots: Mapping[str, Path],
) -> list[OverlayPlan]:
    brain = brain_root.expanduser().resolve()
    matching = [
        overlay
        for overlay in resolved.document.get("runtime_overlays", [])
        if overlay["runtime"] in {"*", runtime}
    ]
    missing_roots = sorted({item["kind"] for item in matching} - set(target_roots))
    if missing_roots:
        raise ProfileError(
            "missing --target-root for overlay kinds: " + ", ".join(missing_roots)
        )

    plans: list[OverlayPlan] = []
    seen_targets: set[Path] = set()
    for overlay in matching:
        source = (brain / overlay["path"]).resolve(strict=False)
        try:
            source.relative_to(brain)
        except ValueError as exc:
            raise ProfileError(f"overlay source escapes the brain: {overlay['path']!r}") from exc
        if not source.exists():
            raise ProfileError(f"overlay source does not exist: {overlay['path']!r}")

        relative_target = _relative_target(overlay["target"])
        root = target_roots[overlay["kind"]].expanduser().resolve(strict=False)
        target = root / relative_target
        _assert_parent_within_root(target, root)
        if target in seen_targets:
            raise ProfileError(f"duplicate overlay destination: {target}")
        seen_targets.add(target)

        quarantine = (
            brain
            / QUARANTINE_DIR
            / runtime
            / resolved.profile_id
            / overlay["kind"]
            / relative_target
        )
        if target.is_symlink():
            try:
                correct = target.resolve(strict=False) == source.resolve(strict=False)
            except OSError:
                correct = False
            action = "unchanged" if correct else "quarantine-link"
        elif target.exists():
            action = "quarantine-link"
        else:
            action = "link"

        if action == "quarantine-link" and (
            quarantine.exists() or quarantine.is_symlink()
        ):
            raise ProfileError(
                f"overlay quarantine destination already exists: {quarantine}"
            )
        plans.append(
            OverlayPlan(
                runtime=runtime,
                kind=overlay["kind"],
                source=source,
                target=target,
                quarantine=quarantine,
                action=action,
            )
        )
    return plans


def apply_overlay_plan(plans: Sequence[OverlayPlan]) -> None:
    for plan in plans:
        if plan.action == "unchanged":
            continue
        quarantined = False
        if plan.action == "quarantine-link":
            plan.quarantine.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(plan.target), str(plan.quarantine))
            quarantined = True
        try:
            plan.target.parent.mkdir(parents=True, exist_ok=True)
            plan.target.symlink_to(
                plan.source,
                target_is_directory=plan.source.is_dir(),
            )
        except OSError:
            if quarantined and not plan.target.exists() and not plan.target.is_symlink():
                shutil.move(str(plan.quarantine), str(plan.target))
            raise


def report_plan(
    reporter: Reporter,
    resolved: ResolvedProfile,
    runtime: str,
    plans: Sequence[OverlayPlan],
    *,
    apply: bool,
) -> None:
    reporter.write("# Profile overlays")
    reporter.write(f"mode: {'apply' if apply else 'dry-run'}")
    reporter.write(f"profile: {resolved.profile_id} ({resolved.source})")
    reporter.write(f"runtime: {runtime}")
    if not plans:
        reporter.write("overlays: none selected for this runtime")
        return
    reporter.write("overlays:")
    for plan in plans:
        reporter.write(f"  {plan.action.upper():15} {plan.kind}: {plan.target}")
        reporter.write(f"    source: {plan.source}")
        if plan.action == "quarantine-link":
            reporter.write(f"    quarantine: {plan.quarantine}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Project private profile resources into runtime target roots"
    )
    parser.add_argument("--brain", required=True, help="Path to the brain root")
    parser.add_argument("--runtime", required=True, help="Active runtime identifier")
    parser.add_argument(
        "--target-root",
        action="append",
        default=[],
        metavar="KIND=PATH",
        help="Runtime adapter target root for rule, skill, agent, or theme",
    )
    parser.add_argument("--profile", help="Explicit profile id")
    parser.add_argument("--cwd", help="Working directory used for profile selection")
    parser.add_argument("--apply", action="store_true", help="Apply the plan")
    args = parser.parse_args()

    reporter = Reporter(Path(__file__).with_suffix(".log"))
    try:
        brain = Path(args.brain).expanduser().resolve()
        if not brain.is_dir():
            raise ProfileError(f"brain directory not found: {brain}")
        target_roots = parse_target_roots(args.target_root)
        resolved = resolve_profile(
            brain,
            explicit_profile=args.profile,
            cwd=Path(args.cwd).expanduser() if args.cwd else None,
        )
        plans = build_overlay_plan(
            brain,
            resolved,
            runtime=args.runtime,
            target_roots=target_roots,
        )
        reporter.write(f"command: {build_command_string()}")
        report_plan(reporter, resolved, args.runtime, plans, apply=args.apply)
        if args.apply:
            apply_overlay_plan(plans)
            reporter.write("Profile overlay projection completed.")
        else:
            reporter.write("Dry run only. Re-run with --apply to execute.")
        reporter.flush()
        return 0
    except (OSError, ProfileError) as exc:
        reporter.write(f"ERROR: {exc}")
        reporter.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import ClassVar, Literal, override

from clause_selection import DocumentData
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from rental_calculations import calculate_initial_payment
from selection_inputs import (
    ProjectEnvelope,
    ProjectTypeManifest,
    SelectionProjectError,
    digest,
    load_yaml,
    resolve,
)

_OVERRIDE_NAME = "defaults.override.yaml"


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class DefaultRules(_FrozenModel):
    deposit_months: Decimal
    additional_guarantee_months: Decimal
    reservation_application_priority: tuple[
        Literal["first-rent", "additional-guarantee", "security-deposit"],
        ...,
    ]
    natural_person_extension_years: int
    legal_person_extension_years: int


class DefaultsPackage(_FrozenModel):
    defaults_version: Literal["0.1.0"]
    profile: str
    data: dict[str, JsonValue]
    rules: DefaultRules


class DefaultsOverride(_FrozenModel):
    data: dict[str, JsonValue] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DefaultsResolution:
    profile: str
    profile_path: Path
    profile_sha256: str
    override_path: Path | None
    override_sha256: str | None


@dataclass(frozen=True, slots=True)
class ResolvedProjectData:
    data: DocumentData
    defaults: DefaultsResolution | None


@dataclass(frozen=True, slots=True)
class UnknownDefaultsProfileError(SelectionProjectError):
    profile: str

    @override
    def __str__(self) -> str:
        return f"project type does not declare defaults profile: {self.profile}"


@dataclass(frozen=True, slots=True)
class PublicationReadinessError(SelectionProjectError):
    document: str
    blockers: tuple[str, ...]

    @override
    def __str__(self) -> str:
        return f"{self.document} publication blocked: {', '.join(self.blockers)}"


@dataclass(frozen=True, slots=True)
class InvalidNumericFieldError(SelectionProjectError):
    field: str

    @override
    def __str__(self) -> str:
        return f"project data field must be numeric: {self.field}"


def _merge(
    base: dict[str, JsonValue],
    overlay: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    merged = dict(base)
    for key, overlay_value in overlay.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(overlay_value, dict):
            merged[key] = (
                dict(overlay_value)
                if "enabled" in overlay_value
                and overlay_value.get("enabled") != base_value.get("enabled")
                else _merge(base_value, overlay_value)
            )
        else:
            merged[key] = overlay_value
    return merged


def _object(root: dict[str, JsonValue], *path: str) -> dict[str, JsonValue]:
    current = root
    for segment in path:
        candidate = current.get(segment)
        if not isinstance(candidate, dict):
            candidate = {}
            current[segment] = candidate
        current = candidate
    return current


def _decimal(node: dict[str, JsonValue], field: str) -> Decimal:
    value = node[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise InvalidNumericFieldError(field=field)
    return Decimal(str(value))


def _derive(
    root: dict[str, JsonValue],
    rules: DefaultRules,
) -> dict[str, JsonValue]:
    operation = _object(root, "operation")
    lease = _object(operation, "lease")
    rent = _decimal(lease, "monthly_rent")
    lease["annual_rent"] = float(rent * Decimal(12))
    _ = lease.setdefault("deposit_amount", float(rent * rules.deposit_months))
    _ = lease.setdefault(
        "additional_guarantee_amount",
        float(rent * rules.additional_guarantee_months),
    )

    landlord_context = _object(lease, "landlord_context")
    legal_form = landlord_context.get("legal_form")
    _ = lease.setdefault(
        "legal_extension_years",
        (
            rules.legal_person_extension_years
            if legal_form == "legal-person"
            else rules.natural_person_extension_years
        ),
    )

    start_value = lease.get("start_date")
    if isinstance(start_value, str):
        start = date.fromisoformat(start_value)
        renewal = start.replace(year=start.year + 1)
        _ = lease.setdefault(
            "first_annual_period_end",
            (renewal - timedelta(days=1)).isoformat(),
        )
        _ = lease.setdefault("first_renewal_date", renewal.isoformat())
        first_full_month = (
            start
            if start.day == 1
            else date(
                start.year + (1 if start.month == 12 else 0),
                1 if start.month == 12 else start.month + 1,
                1,
            )
        )
        due_day = lease.get("payment_due_day")
        if isinstance(due_day, int):
            _ = lease.setdefault(
                "first_full_rent_due_date",
                first_full_month.replace(
                    day=min(
                        due_day,
                        calendar.monthrange(
                            first_full_month.year,
                            first_full_month.month,
                        )[1],
                    ),
                ).isoformat(),
            )

    reservation = operation.get("reservation")
    if isinstance(reservation, dict):
        _ = reservation.setdefault(
            "application_priority",
            list(rules.reservation_application_priority),
        )
        payment = calculate_initial_payment(
            monthly_rent=rent,
            reservation_amount=_decimal(reservation, "amount"),
            deposit_amount=_decimal(lease, "deposit_amount"),
            additional_guarantee_amount=_decimal(
                lease,
                "additional_guarantee_amount",
            ),
            lease_start=str(lease["start_date"]),
        )
        lease["initial_payment"] = {
            "prorated_first_rent": float(payment.prorated_first_rent),
            "reservation_applied": float(payment.reservation_applied),
            "remaining_first_rent": float(payment.remaining_first_rent),
            "total_due_at_signature": float(payment.total_due_at_signature),
        }
    return root


def resolve_project_data(
    manifest_path: Path,
    data_path: Path,
) -> ResolvedProjectData:
    manifest = load_yaml(manifest_path, ProjectTypeManifest)
    instance = load_yaml(data_path, DocumentData)
    project = ProjectEnvelope.model_validate(instance.root).project
    if project.defaults_profile is None:
        return ResolvedProjectData(data=instance, defaults=None)
    try:
        profile_ref = manifest.defaults_profiles[project.defaults_profile]
    except KeyError:
        raise UnknownDefaultsProfileError(profile=project.defaults_profile) from None

    profile_path = resolve(profile_ref, manifest_path.parent)
    package = load_yaml(profile_path, DefaultsPackage)
    merged = _merge(package.data, instance.root)
    override_path = data_path.parent / _OVERRIDE_NAME
    override_sha256: str | None = None
    if override_path.is_file():
        override = load_yaml(override_path, DefaultsOverride)
        merged = _merge(package.data, override.data)
        merged = _merge(merged, instance.root)
        override_sha256 = digest(override_path)
    return ResolvedProjectData(
        data=DocumentData.model_validate(_derive(merged, package.rules)),
        defaults=DefaultsResolution(
            profile=package.profile,
            profile_path=profile_path,
            profile_sha256=digest(profile_path),
            override_path=override_path if override_path.is_file() else None,
            override_sha256=override_sha256,
        ),
    )


def reservation_publication_blockers(data: DocumentData) -> tuple[str, ...]:
    operation = data.root.get("operation")
    if not isinstance(operation, dict):
        return ("reservation-data-missing",)
    reservation = operation.get("reservation")
    if not isinstance(reservation, dict):
        return ("reservation-data-missing",)
    blockers: list[str] = []
    payment_terms = reservation.get("payment_terms")
    if not isinstance(payment_terms, dict) or payment_terms.get("mode") == "pending":
        blockers.append("reservation-payment-mode-unresolved")
    return tuple(blockers)


def require_publication_ready(data: DocumentData, document: str) -> None:
    blockers = (
        reservation_publication_blockers(data) if document == "reservation" else ()
    )
    if blockers:
        raise PublicationReadinessError(document=document, blockers=blockers)

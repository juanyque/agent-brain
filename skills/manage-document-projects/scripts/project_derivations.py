from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import ClassVar, Literal, override

from pydantic import BaseModel, ConfigDict, JsonValue
from rental_calculations import calculate_initial_payment
from selection_inputs import SelectionProjectError


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


@dataclass(frozen=True, slots=True)
class InvalidNumericFieldError(SelectionProjectError):
    field: str

    @override
    def __str__(self) -> str:
        return f"project data field must be numeric: {self.field}"


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


def derive_project_data(
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
    if isinstance(reservation, dict) and "amount" in reservation:
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

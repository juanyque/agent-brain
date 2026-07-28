from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from document_formatting import rounded_money


@dataclass(frozen=True, slots=True)
class InitialPayment:
    prorated_first_rent: Decimal
    reservation_applied: Decimal
    remaining_first_rent: Decimal
    total_due_at_signature: Decimal


def calculate_initial_payment(
    *,
    monthly_rent: Decimal,
    reservation_amount: Decimal,
    deposit_amount: Decimal,
    additional_guarantee_amount: Decimal,
    lease_start: str | date,
) -> InitialPayment:
    start = date.fromisoformat(lease_start) if isinstance(lease_start, str) else lease_start
    days_in_month = calendar.monthrange(start.year, start.month)[1]
    occupied_days = days_in_month - start.day + 1
    prorated = rounded_money(
        monthly_rent * Decimal(occupied_days) / Decimal(days_in_month),
    )
    reservation_applied = min(reservation_amount, prorated)
    remaining_first_rent = rounded_money(prorated - reservation_applied)
    total = rounded_money(
        remaining_first_rent + deposit_amount + additional_guarantee_amount,
    )
    return InitialPayment(
        prorated_first_rent=prorated,
        reservation_applied=rounded_money(reservation_applied),
        remaining_first_rent=remaining_first_rent,
        total_due_at_signature=total,
    )

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


@dataclass(frozen=True, slots=True)
class TerminationSettlement:
    months_elapsed: int
    days_elapsed: int
    is_within_mandatory_period: bool
    mandatory_stay_months: int
    compensation_amount: Decimal
    compensation_reason: str
    total_guarantees: Decimal
    deposit_refund_amount: Decimal



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


def calculate_termination_settlement(
    *,
    monthly_rent: Decimal,
    deposit_amount: Decimal,
    additional_guarantee_amount: Decimal,
    lease_start: str | date,
    termination_date: str | date,
    minimum_stay_months: int = 6,
    compensation_type: str = "one-month-per-remaining-year",
) -> TerminationSettlement:
    start = date.fromisoformat(lease_start) if isinstance(lease_start, str) else lease_start
    end = date.fromisoformat(termination_date) if isinstance(termination_date, str) else termination_date

    total_guarantees = deposit_amount + additional_guarantee_amount

    # Calculate months elapsed approximately and days elapsed
    days_elapsed = (end - start).days
    # Exact 6-month date
    month_target = start.month + minimum_stay_months
    year_target = start.year + (month_target - 1) // 12
    month_target = ((month_target - 1) % 12) + 1
    day_target = min(start.day, calendar.monthrange(year_target, month_target)[1])
    mandatory_end_date = date(year_target, month_target, day_target)

    is_within_mandatory = end < mandatory_end_date

    # Calculate 1-year mark for LAU compensation
    year1_end = date(start.year + 1, start.month, min(start.day, calendar.monthrange(start.year + 1, start.month)[1]))

    if is_within_mandatory:
        # Breach of mandatory period: rent up to 6th month or agreed damages
        # Under Art. 11 LAU, tenant cannot unilaterally withdraw before 6 months.
        # If agreed by parties, compensation covers remaining unfulfilled mandatory rent
        # or proportional year 1 compensation.
        remaining_mandatory_days = (mandatory_end_date - end).days
        comp_amount = rounded_money(
            monthly_rent * Decimal(remaining_mandatory_days) / Decimal("30.416"),
        )
        reason = f"Incumplimiento del periodo obligatorio de {minimum_stay_months} meses (hasta {mandatory_end_date.strftime('%d/%m/%Y')})"
    elif end < year1_end and compensation_type == "one-month-per-remaining-year":
        remaining_days_year1 = (year1_end - end).days
        comp_amount = rounded_money(
            monthly_rent * Decimal(remaining_days_year1) / Decimal(365),
        )
        reason = f"Desistimiento anticipado en año 1 ({remaining_days_year1} días restantes de la primera anualidad)"
    else:
        comp_amount = Decimal("0.00")
        reason = "Desistimiento libre tras el primer año o sin penalización pactada"

    refund = rounded_money(max(Decimal("0.00"), total_guarantees - comp_amount))

    return TerminationSettlement(
        months_elapsed=int(days_elapsed // 30.416),
        days_elapsed=days_elapsed,
        is_within_mandatory_period=is_within_mandatory,
        mandatory_stay_months=minimum_stay_months,
        compensation_amount=comp_amount,
        compensation_reason=reason,
        total_guarantees=total_guarantees,
        deposit_refund_amount=refund,
    )

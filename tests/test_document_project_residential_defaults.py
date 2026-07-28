from __future__ import annotations

import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import yaml
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "manage-document-projects"
PACKAGE = SKILL / "assets" / "project-types" / "residential-lease"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

from clause_selection import DocumentData
from document_formatting import es_date, es_iban, es_money, es_number
from project_defaults import reservation_publication_blockers, resolve_project_data
from rental_calculations import calculate_initial_payment

INITIALIZER = SCRIPTS / "init_document_project.py"


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")


class _PaymentTerms(_FrozenModel):
    mode: str
    business_days: int


class _Reservation(_FrozenModel):
    payment_terms: _PaymentTerms
    application_priority: tuple[str, ...]
    insurance: dict[str, str]


class _InitialPayment(_FrozenModel):
    prorated_first_rent: float
    reservation_applied: float
    remaining_first_rent: float
    total_due_at_signature: float


class _RentUpdate(_FrozenModel):
    reference_index: str
    positive_variations_only: bool


class _Withdrawal(_FrozenModel):
    minimum_stay_months: int


class _Lease(_FrozenModel):
    payment_due_day: int
    annual_rent: float
    deposit_amount: float
    additional_guarantee_amount: float
    initial_payment: _InitialPayment
    first_full_rent_due_date: str
    rent_update: _RentUpdate
    withdrawal: _Withdrawal


class _Operation(_FrozenModel):
    lease: _Lease
    reservation: _Reservation


class _Fixture(_FrozenModel):
    operation: _Operation


def test_residential_fixture_inherits_defaults_and_calculates_initial_payment() -> None:
    resolved = resolve_project_data(
        PACKAGE / "project-type.yaml",
        PACKAGE / "examples" / "minimal-project.yaml",
    )

    fixture = _Fixture.model_validate(resolved.data.root)
    lease = fixture.operation.lease
    reservation = fixture.operation.reservation
    assert lease.payment_due_day == 5
    assert lease.annual_rent == 119988
    assert lease.deposit_amount == 9999
    assert lease.additional_guarantee_amount == 9999
    assert lease.rent_update == _RentUpdate(
        reference_index="cpi",
        positive_variations_only=True,
    )
    assert lease.withdrawal.minimum_stay_months == 12
    assert reservation.payment_terms.business_days == 2
    assert reservation.application_priority == (
        "first-rent",
        "additional-guarantee",
        "security-deposit",
    )
    assert lease.initial_payment == _InitialPayment(
        prorated_first_rent=5713.71,
        reservation_applied=5555,
        remaining_first_rent=158.71,
        total_due_at_signature=20156.71,
    )
    assert lease.first_full_rent_due_date == "2026-03-05"
    assert resolved.defaults is not None
    assert resolved.defaults.profile == "residential-standard"
    assert resolved.defaults.override_path is None


def test_brain_local_override_wins_without_changing_skill_defaults() -> None:
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        data = workspace / "project-data.yaml"
        override = workspace / "defaults.override.yaml"
        _ = data.write_text(
            (PACKAGE / "examples" / "minimal-project.yaml").read_text(
                encoding="utf-8",
            ),
            encoding="utf-8",
        )
        _ = override.write_text(
            yaml.safe_dump(
                {
                    "data": {
                        "operation": {
                            "lease": {
                                "payment_due_day": 7,
                            },
                        },
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        resolved = resolve_project_data(PACKAGE / "project-type.yaml", data)

        fixture = _Fixture.model_validate(resolved.data.root)
        assert fixture.operation.lease.payment_due_day == 7
        assert resolved.defaults is not None
        assert resolved.defaults.override_path == override


def test_initial_payment_uses_decimal_half_up_and_inclusive_calendar_days() -> None:
    payment = calculate_initial_payment(
        monthly_rent=Decimal("9999.00"),
        reservation_amount=Decimal("5555.00"),
        deposit_amount=Decimal("9999.00"),
        additional_guarantee_amount=Decimal("9999.00"),
        lease_start="2026-02-13",
    )

    assert payment.prorated_first_rent == Decimal("5713.71")
    assert payment.remaining_first_rent == Decimal("158.71")
    assert payment.total_due_at_signature == Decimal("20156.71")


def test_spanish_document_filters_are_deterministic() -> None:
    assert es_date("2026-02-13") == "13/02/2026"
    assert es_money(Decimal(9999)) == "9.999,00 €"
    assert es_number(Decimal("777777.77")) == "777.777,77"
    assert es_iban("ES1234567890123456789012") == "ES12 3456 7890 1234 5678 9012"


def test_reservation_fixture_keeps_payment_selected_and_insurance_pending() -> None:
    resolved = resolve_project_data(
        PACKAGE / "project-type.yaml",
        PACKAGE / "examples" / "minimal-project.yaml",
    )

    fixture = _Fixture.model_validate(resolved.data.root)
    reservation = fixture.operation.reservation
    assert reservation.payment_terms.mode == "bank-transfer"
    assert reservation.insurance == {"status": "pending"}
    assert reservation_publication_blockers(resolved.data) == ()


def test_reservation_publication_reports_only_unresolved_payment() -> None:
    pending = DocumentData.model_validate(
        {
            "operation": {
                "reservation": {
                    "payment_terms": {
                        "mode": "pending",
                        "business_days": 2,
                    },
                    "insurance": {
                        "status": "pending",
                    },
                },
            },
        },
    )

    assert reservation_publication_blockers(pending) == (
        "reservation-payment-mode-unresolved",
    )


def test_initializer_creates_an_idempotent_brain_local_override() -> None:
    with tempfile.TemporaryDirectory() as raw:
        project = Path(raw) / "residential-project"

        first = subprocess.run(
            ["uv", "run", "--script", str(INITIALIZER), str(project), "--apply"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        target = project / "data" / "defaults.override.yaml"
        original = target.read_bytes()
        second = subprocess.run(
            ["uv", "run", "--script", str(INITIALIZER), str(project), "--apply"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert first.returncode == 0, first.stdout + first.stderr
        assert second.returncode == 0, second.stdout + second.stderr
        assert target.read_bytes() == original
        assert yaml.safe_load(original) == {"data": {}}
        assert "unchanged" in second.stdout

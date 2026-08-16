from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import override

_CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class InvalidDecimalValueError(ValueError):
    value: str

    @override
    def __str__(self) -> str:
        return f"not a decimal value: {self.value}"


def _decimal(value: Decimal | float | str) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise InvalidDecimalValueError(value=str(value)) from error


def _grouped(value: Decimal, decimal_places: int) -> str:
    quantizer = Decimal(1).scaleb(-decimal_places)
    rendered = f"{value.quantize(quantizer, rounding=ROUND_HALF_UP):,.{decimal_places}f}"
    return rendered.replace(",", "_").replace(".", ",").replace("_", ".")


def es_date(value: date | str) -> str:
    parsed = value if isinstance(value, date) else date.fromisoformat(value)
    return parsed.strftime("%d/%m/%Y")


def es_money(value: Decimal | float | str | None) -> str:
    if value is None:
        return "____________________ €"
    if isinstance(value, str) and (value.strip() == "" or "_" in value):
        return value if "€" in value else f"{value} €"
    return f"{_grouped(_decimal(value), 2)} €"


def es_number(value: Decimal | float | str | None) -> str:
    if value is None:
        return "____________________"
    if isinstance(value, str) and (value.strip() == "" or "_" in value):
        return value
    return _grouped(_decimal(value), 2)


def es_iban(value: str) -> str:
    compact = "".join(value.split()).upper()
    return " ".join(compact[index : index + 4] for index in range(0, len(compact), 4))


def rounded_money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)

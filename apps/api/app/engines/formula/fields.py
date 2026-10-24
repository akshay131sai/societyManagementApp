"""The field registry.

Every name a formula may reference is declared here, once. The validator, the
evaluator and the frontend's component palette are all driven by this table, so
a formula cannot reference a field that does not exist and the Bill Builder
cannot offer one.

Adding a billing input is a two-line change here plus a line in
``BillingContextBuilder`` — never a new special case in the evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class FieldKind(StrEnum):
    MONEY = "MONEY"
    """Rupees. Rendered with ₹ and 2 dp."""
    QUANTITY = "QUANTITY"
    """A measured amount — sqft, KL, units."""
    COUNT = "COUNT"
    """A whole number of things."""
    TEXT = "TEXT"
    """Only comparable with EQ / NEQ."""
    BOOLEAN = "BOOLEAN"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    key: str
    label: str
    kind: FieldKind
    unit: str | None
    description: str
    group: str
    default: Decimal | str | bool
    """Used when a flat has no value — a missing water reading must not abort a
    400-flat run, and 0 is the honest answer for "no consumption recorded"."""


def _f(
    key: str,
    label: str,
    kind: FieldKind,
    group: str,
    description: str,
    unit: str | None = None,
    default: Decimal | str | bool = Decimal(0),
) -> FieldSpec:
    return FieldSpec(key, label, kind, unit, description, group, default)


FIELDS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in (
        # --- Flat ---------------------------------------------------------
        _f("flat_area", "Flat area", FieldKind.QUANTITY, "Flat",
           "Built-up area of the flat", "sqft"),
        _f("carpet_area", "Carpet area", FieldKind.QUANTITY, "Flat",
           "Carpet area, where recorded", "sqft"),
        _f("floor_number", "Floor number", FieldKind.COUNT, "Flat",
           "0 is ground, negative is basement"),
        _f("flat_type", "Flat type", FieldKind.TEXT, "Flat",
           "e.g. 2BHK — compare with EQ", default=""),
        _f("occupancy_status", "Occupancy", FieldKind.TEXT, "Flat",
           "VACANT / OWNER_OCCUPIED / RENTED", default="VACANT"),
        _f("is_vacant", "Is vacant", FieldKind.BOOLEAN, "Flat",
           "True when nobody lives there", default=False),
        _f("is_rented", "Is rented", FieldKind.BOOLEAN, "Flat",
           "True when a tenant lives there", default=False),

        # --- Maintenance --------------------------------------------------
        _f("base_maintenance", "Base maintenance", FieldKind.MONEY, "Maintenance",
           "The flat's override, or the template's base_maintenance parameter", "₹"),

        # --- Water --------------------------------------------------------
        _f("water_consumption", "Water consumed", FieldKind.QUANTITY, "Water",
           "Consumption for the billing period", "KL"),
        _f("water_previous", "Water — previous reading", FieldKind.QUANTITY, "Water",
           "Meter reading at the start of the period", "KL"),
        _f("water_current", "Water — current reading", FieldKind.QUANTITY, "Water",
           "Meter reading at the end of the period", "KL"),

        # --- Electricity --------------------------------------------------
        _f("electricity_units", "Electricity consumed", FieldKind.QUANTITY, "Electricity",
           "Units consumed for the billing period", "kWh"),
        _f("electricity_amount", "Electricity amount", FieldKind.MONEY, "Electricity",
           "Amount recorded against the reading, when metered externally", "₹"),

        # --- Parking & vehicles -------------------------------------------
        _f("parking_slot_count", "Parking slots", FieldKind.COUNT, "Parking",
           "Slots allotted to this flat"),
        _f("parking_charge_total", "Parking charges", FieldKind.MONEY, "Parking",
           "Sum of the monthly charge on each allotted slot", "₹"),
        _f("vehicle_count", "Vehicles", FieldKind.COUNT, "Parking",
           "Registered vehicles for this flat"),
        _f("two_wheeler_count", "Two-wheelers", FieldKind.COUNT, "Parking",
           "Registered two-wheelers"),
        _f("four_wheeler_count", "Four-wheelers", FieldKind.COUNT, "Parking",
           "Registered four-wheelers"),

        # --- Pets ---------------------------------------------------------
        _f("pet_count", "Pets", FieldKind.COUNT, "Pets", "Registered pets"),
        _f("pet_fee_total", "Pet fees", FieldKind.MONEY, "Pets",
           "Sum of the monthly fee on each registered pet", "₹"),

        # --- Residents ----------------------------------------------------
        _f("resident_count", "Residents", FieldKind.COUNT, "Residents",
           "Active residents living in the flat"),

        # --- History ------------------------------------------------------
        _f("outstanding_balance", "Outstanding", FieldKind.MONEY, "History",
           "Unpaid amount carried from earlier published bills", "₹"),
        _f("days_overdue", "Days overdue", FieldKind.COUNT, "History",
           "Days past the due date of the oldest unpaid bill"),

        # --- Period -------------------------------------------------------
        _f("period_months", "Months in period", FieldKind.COUNT, "Period",
           "1 monthly, 3 quarterly, 6 half-yearly, 12 yearly", default=Decimal(1)),
    )
}

NUMERIC_KINDS = frozenset({FieldKind.MONEY, FieldKind.QUANTITY, FieldKind.COUNT})

FIELD_GROUPS: tuple[str, ...] = (
    "Maintenance",
    "Flat",
    "Water",
    "Electricity",
    "Parking",
    "Pets",
    "Residents",
    "History",
    "Period",
)


def is_known(key: str) -> bool:
    """Whether a field name exists, including a ``custom.*`` template parameter."""
    return key in FIELDS or key.startswith("custom.")


def spec_for(key: str) -> FieldSpec | None:
    return FIELDS.get(key)


def is_numeric(key: str) -> bool:
    """Custom parameters are always numeric; declared fields depend on kind."""
    if key.startswith("custom."):
        return True
    spec = FIELDS.get(key)
    return spec is not None and spec.kind in NUMERIC_KINDS


def is_boolean(key: str) -> bool:
    spec = FIELDS.get(key)
    return spec is not None and spec.kind is FieldKind.BOOLEAN


def catalogue() -> list[dict[str, object]]:
    """Serialisable field list, for the Bill Builder palette."""
    return [
        {
            "key": s.key,
            "label": s.label,
            "kind": s.kind.value,
            "unit": s.unit,
            "description": s.description,
            "group": s.group,
        }
        for s in sorted(FIELDS.values(), key=lambda s: (FIELD_GROUPS.index(s.group), s.label))
    ]

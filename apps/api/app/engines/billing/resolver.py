"""Template assignment resolution.

"Which template billed this flat" is the first question asked when a bill looks
wrong, so resolution is a **pure function** with its own tests rather than a
query buried in a service.

Most specific scope wins; ``priority`` breaks ties; the newest assignment breaks
a remaining tie so the answer is always deterministic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models.tenant import (
    SCOPE_SPECIFICITY,
    AssignmentScope,
    BillTemplateAssignment,
    Flat,
)


@dataclass(frozen=True, slots=True)
class FlatScope:
    """Just enough of a flat to resolve an assignment against."""

    flat_id: uuid.UUID
    building_id: uuid.UUID
    block_id: uuid.UUID
    flat_type: str | None

    @classmethod
    def of(cls, flat: Flat) -> FlatScope:
        return cls(flat.id, flat.building_id, flat.block_id, flat.flat_type)


def matches(assignment: BillTemplateAssignment, scope: FlatScope) -> bool:
    match assignment.scope:
        case AssignmentScope.ALL:
            return True
        case AssignmentScope.BUILDING:
            return assignment.building_id == scope.building_id
        case AssignmentScope.BLOCK:
            return assignment.block_id == scope.block_id
        case AssignmentScope.FLAT_TYPE:
            return (
                scope.flat_type is not None
                and assignment.flat_type is not None
                and assignment.flat_type.lower() == scope.flat_type.lower()
            )
        case AssignmentScope.FLAT:
            return assignment.flat_id == scope.flat_id
        case _:  # pragma: no cover - the enum is closed
            return False


def resolve_for_flat(
    assignments: list[BillTemplateAssignment], scope: FlatScope
) -> BillTemplateAssignment | None:
    """The single assignment that governs this flat, or None."""
    candidates = [a for a in assignments if a.is_active and matches(a, scope)]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda a: (
            SCOPE_SPECIFICITY[a.scope],
            a.priority,
            a.created_at,
        ),
    )


def applicable_flats(
    assignments: list[BillTemplateAssignment],
    flats: list[Flat],
    template_id: uuid.UUID,
) -> list[Flat]:
    """Flats this template governs.

    A flat covered by a broader assignment of *this* template but a more
    specific assignment of *another* template belongs to the other one — which
    is what makes "3BHK flats bill differently" work without excluding them by
    hand from the society-wide template.
    """
    return [
        flat
        for flat in flats
        if (winner := resolve_for_flat(assignments, FlatScope.of(flat))) is not None
        and winner.template_id == template_id
    ]


def explain(
    assignments: list[BillTemplateAssignment], scope: FlatScope
) -> list[dict[str, object]]:
    """Every matching assignment, ranked — for answering "why this template?"."""
    ranked = sorted(
        (a for a in assignments if a.is_active and matches(a, scope)),
        key=lambda a: (SCOPE_SPECIFICITY[a.scope], a.priority, a.created_at),
        reverse=True,
    )
    return [
        {
            "assignment_id": str(a.id),
            "template_id": str(a.template_id),
            "scope": a.scope.value,
            "priority": a.priority,
            "specificity": SCOPE_SPECIFICITY[a.scope],
            "wins": i == 0,
        }
        for i, a in enumerate(ranked)
    ]

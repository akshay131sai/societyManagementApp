"""visitor guard decisions

Records *how* a visitor was let in or turned away, so a guard who calls the
flat and hears "yes, send him up" can act on it, and the flat can see that the
yes was taken over the phone and by whom.

``approved_via`` is a short string with a check constraint rather than a PG
enum: three values, all in this table, and adding a fourth later should not
need an ``ALTER TYPE`` dance.

``guard_cannot_self_admit`` is the rule the feature exists to enforce. A guard
may turn anyone away on their own judgement; they may only admit someone the
flat has said yes to.

Revision ID: e7b3d5a1c9f2
Revises: c4f1a7b92e30
Create Date: 2026-10-09 16:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e7b3d5a1c9f2'
down_revision: str | None = 'c4f1a7b92e30'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('visitors', sa.Column('approved_via', sa.String(length=20), nullable=True))
    op.add_column('visitors', sa.Column('confirmed_with', sa.String(length=150), nullable=True))

    # Every decision made before this column existed was made in the app.
    op.execute("UPDATE visitors SET approved_via = 'APP' WHERE approved_at IS NOT NULL")

    op.create_check_constraint(
        'ck_visitors_approved_via_values',
        'visitors',
        "approved_via IS NULL OR approved_via IN ('APP', 'PHONE', 'GUARD')",
    )
    op.create_check_constraint(
        'ck_visitors_phone_needs_resident',
        'visitors',
        "approved_via IS DISTINCT FROM 'PHONE' OR confirmed_with IS NOT NULL",
    )
    op.create_check_constraint(
        'ck_visitors_guard_cannot_self_admit',
        'visitors',
        "approved_via IS DISTINCT FROM 'GUARD' OR status <> 'APPROVED'",
    )


def downgrade() -> None:
    op.drop_constraint('ck_visitors_guard_cannot_self_admit', 'visitors', type_='check')
    op.drop_constraint('ck_visitors_phone_needs_resident', 'visitors', type_='check')
    op.drop_constraint('ck_visitors_approved_via_values', 'visitors', type_='check')
    op.drop_column('visitors', 'confirmed_with')
    op.drop_column('visitors', 'approved_via')

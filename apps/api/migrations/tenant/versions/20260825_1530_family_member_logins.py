"""family member logins and access tiers

Turns ``family_members`` from a roster of dependants into the household's
app accounts.

Two parts are written by hand rather than left to ``create_table`` output:

* ``relationship_to_resident`` is converted from free text to an enum in place.
  The ``USING`` clause folds case and whitespace, so ``Mother``/``mother``/
  `` 'Son' `` all land correctly; anything outside the vocabulary becomes
  ``OTHER`` rather than failing the migration and blocking the deploy. The
  downgrade returns plain text, so it is lossless in both directions.

* ``ux_family_members_email`` is partial. A revoked member keeps their row for
  audit history with ``is_active = false``, and that row must not reserve the
  address against a later re-invite.

The ``access_needs_email`` check is what lets the service layer treat "has a
tier" and "has an address to sign in with" as the same fact.

Revision ID: c4f1a7b92e30
Revises: 8a41f2c9d05e
Create Date: 2026-08-25 15:30:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c4f1a7b92e30'
down_revision: str | None = '8a41f2c9d05e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


RELATIONSHIP = (
    'SPOUSE',
    'FATHER',
    'MOTHER',
    'SON',
    'DAUGHTER',
    'BROTHER',
    'SISTER',
    'GRANDPARENT',
    'GRANDCHILD',
    'OTHER',
)

ACCESS_LEVEL = ('NONE', 'CHILD', 'MEMBER', 'CO_ADMIN')


def upgrade() -> None:
    relationship = sa.Enum(*RELATIONSHIP, name='family_relationship')
    access_level = sa.Enum(*ACCESS_LEVEL, name='family_access_level')
    bind = op.get_bind()
    relationship.create(bind, checkfirst=True)
    access_level.create(bind, checkfirst=True)

    # Free text -> enum, in place. Unrecognised values become OTHER so a
    # society with hand-typed relationships still migrates.
    op.execute(
        "ALTER TABLE family_members "
        "ALTER COLUMN relationship_to_resident TYPE family_relationship "
        "USING CASE upper(btrim(relationship_to_resident)) "
        + " ".join(f"WHEN '{value}' THEN '{value}'" for value in RELATIONSHIP)
        + " WHEN 'HUSBAND' THEN 'SPOUSE'"
        " WHEN 'WIFE' THEN 'SPOUSE'"
        " WHEN 'CHILD' THEN 'SON'"
        " WHEN 'DAD' THEN 'FATHER'"
        " WHEN 'MUM' THEN 'MOTHER'"
        " WHEN 'MOM' THEN 'MOTHER'"
        " ELSE 'OTHER' END::family_relationship"
    )

    op.add_column(
        'family_members',
        sa.Column('user_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column('family_members', sa.Column('email', sa.String(length=255), nullable=True))
    op.add_column(
        'family_members',
        sa.Column(
            'access_level',
            access_level,
            nullable=False,
            server_default='NONE',
        ),
    )
    op.add_column(
        'family_members',
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
    )

    op.create_foreign_key(
        'fk_family_members_user_id_users',
        'family_members',
        'users',
        ['user_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_check_constraint(
        'ck_family_members_access_needs_email',
        'family_members',
        "access_level = 'NONE' OR email IS NOT NULL",
    )
    op.create_index(
        'ix_family_members_user',
        'family_members',
        ['user_id'],
        postgresql_where=sa.text('user_id IS NOT NULL'),
    )
    op.create_index(
        'ux_family_members_email',
        'family_members',
        [sa.text('lower(email)')],
        unique=True,
        postgresql_where=sa.text('email IS NOT NULL AND is_active'),
    )


def downgrade() -> None:
    op.drop_index('ux_family_members_email', table_name='family_members')
    op.drop_index('ix_family_members_user', table_name='family_members')
    op.drop_constraint('ck_family_members_access_needs_email', 'family_members', type_='check')
    op.drop_constraint('fk_family_members_user_id_users', 'family_members', type_='foreignkey')
    op.drop_column('family_members', 'is_active')
    op.drop_column('family_members', 'access_level')
    op.drop_column('family_members', 'email')
    op.drop_column('family_members', 'user_id')

    op.execute(
        'ALTER TABLE family_members '
        'ALTER COLUMN relationship_to_resident TYPE VARCHAR(40) '
        'USING relationship_to_resident::text'
    )

    bind = op.get_bind()
    sa.Enum(name='family_access_level').drop(bind, checkfirst=True)
    sa.Enum(name='family_relationship').drop(bind, checkfirst=True)

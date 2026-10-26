"""platform user passwords

Revision ID: 8f3d2c6a1b57
Revises: 5c1e7a2b9d40
Create Date: 2026-10-27 10:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
revision: str = '8f3d2c6a1b57'
down_revision: str | None = '5c1e7a2b9d40'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('platform_users', sa.Column('password_hash', sa.String(length=255), nullable=True))
    op.add_column('platform_users', sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('platform_users', 'password_changed_at')
    op.drop_column('platform_users', 'password_hash')

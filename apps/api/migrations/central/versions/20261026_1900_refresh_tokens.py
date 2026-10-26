"""refresh tokens

Revision ID: 5c1e7a2b9d40
Revises: 93871550da8a
Create Date: 2026-10-26 19:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = '5c1e7a2b9d40'
down_revision: str | None = '93871550da8a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('refresh_tokens',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('platform_user_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('family_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replaced_by', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['platform_user_id'], ['platform_users.id'], name=op.f('fk_refresh_tokens_platform_user_id_platform_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens'))
    )
    op.create_index('ix_refresh_tokens_user', 'refresh_tokens', ['platform_user_id'], unique=False)
    op.create_index('ix_refresh_tokens_family', 'refresh_tokens', ['family_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_refresh_tokens_family', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_user', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')

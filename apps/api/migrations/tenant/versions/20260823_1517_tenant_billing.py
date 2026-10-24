"""tenant billing

Revision ID: fbc6b678f843
Revises: 4d789af9e3e6
Create Date: 2026-08-23 15:17:14.357464
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = 'fbc6b678f843'
down_revision: str | None = '4d789af9e3e6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None



# --------------------------------------------------------------------------- #
# Immutability triggers.
#
# Kept as module constants so the SQL stays readable and the migration body
# stays a list of steps rather than a wall of quoted PL/pgSQL.
# --------------------------------------------------------------------------- #

TEMPLATE_VERSION_IMMUTABLE_FN = """
CREATE OR REPLACE FUNCTION nf_template_version_immutable()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.is_published THEN
        RAISE EXCEPTION
            'Template version % is published and cannot be modified. '
            'Create a new version instead.', OLD.version_number
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;
"""

TEMPLATE_VERSION_IMMUTABLE_TRG = """
CREATE TRIGGER trg_template_version_immutable
BEFORE UPDATE ON bill_template_versions
FOR EACH ROW EXECUTE FUNCTION nf_template_version_immutable();
"""

TEMPLATE_VERSION_NO_DELETE_FN = """
CREATE OR REPLACE FUNCTION nf_template_version_no_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.is_published THEN
        RAISE EXCEPTION
            'Template version % is published and cannot be deleted.',
            OLD.version_number
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
END;
$$;
"""

TEMPLATE_VERSION_NO_DELETE_TRG = """
CREATE TRIGGER trg_template_version_no_delete
BEFORE DELETE ON bill_template_versions
FOR EACH ROW EXECUTE FUNCTION nf_template_version_no_delete();
"""

BILL_GUARD_FN = """
CREATE OR REPLACE FUNCTION nf_bill_guard()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'DRAFT' OR OLD.status = 'FAILED' THEN
        RETURN NEW;   -- a draft may still be edited or discarded
    END IF;

    -- PUBLISHED -> VOID is the one status change allowed.
    IF NEW.status IS DISTINCT FROM OLD.status
       AND NOT (OLD.status = 'PUBLISHED' AND NEW.status = 'VOID') THEN
        RAISE EXCEPTION
            'Bill % is published; its status cannot change to %.',
            OLD.bill_number, NEW.status
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF  NEW.total               IS DISTINCT FROM OLD.total
     OR NEW.subtotal            IS DISTINCT FROM OLD.subtotal
     OR NEW.penalty             IS DISTINCT FROM OLD.penalty
     OR NEW.discount            IS DISTINCT FROM OLD.discount
     OR NEW.tax                 IS DISTINCT FROM OLD.tax
     OR NEW.formula_snapshot    IS DISTINCT FROM OLD.formula_snapshot
     OR NEW.input_snapshot      IS DISTINCT FROM OLD.input_snapshot
     OR NEW.calculation_trace   IS DISTINCT FROM OLD.calculation_trace
     OR NEW.template_version_id IS DISTINCT FROM OLD.template_version_id
     OR NEW.flat_id             IS DISTINCT FROM OLD.flat_id
     OR NEW.period_key          IS DISTINCT FROM OLD.period_key
     OR NEW.bill_number         IS DISTINCT FROM OLD.bill_number
    THEN
        RAISE EXCEPTION
            'Bill % is published and cannot be modified. '
            'Issue a credit note instead.', OLD.bill_number
            USING ERRCODE = 'restrict_violation';
    END IF;

    RETURN NEW;   -- amount_paid / payment_status / paid_at may change
END;
$$;
"""

BILL_GUARD_TRG = """
CREATE TRIGGER trg_bill_guard
BEFORE UPDATE ON maintenance_bills
FOR EACH ROW EXECUTE FUNCTION nf_bill_guard();
"""

BILL_NO_DELETE_FN = """
CREATE OR REPLACE FUNCTION nf_bill_no_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'PUBLISHED' THEN
        RAISE EXCEPTION
            'Bill % is published and cannot be deleted. Void it instead.',
            OLD.bill_number
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
END;
$$;
"""

BILL_NO_DELETE_TRG = """
CREATE TRIGGER trg_bill_no_delete
BEFORE DELETE ON maintenance_bills
FOR EACH ROW EXECUTE FUNCTION nf_bill_no_delete();
"""

LINE_ITEM_GUARD_FN = """
CREATE OR REPLACE FUNCTION nf_line_item_guard()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent_status text;
BEGIN
    SELECT status INTO parent_status FROM maintenance_bills
     WHERE id = COALESCE(NEW.bill_id, OLD.bill_id);
    IF parent_status = 'PUBLISHED' THEN
        RAISE EXCEPTION
            'This bill is published; its line items cannot be changed.'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;
"""

LINE_ITEM_GUARD_TRG = """
CREATE TRIGGER trg_line_item_guard
BEFORE UPDATE OR DELETE ON bill_line_items
FOR EACH ROW EXECUTE FUNCTION nf_line_item_guard();
"""


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('bill_templates',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('frequency', postgresql.ENUM('MONTHLY', 'QUARTERLY', 'HALF_YEARLY', 'YEARLY', 'ONE_TIME',
                    name='billing_frequency', create_type=False), server_default='MONTHLY', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('active_version_id', sa.UUID(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['active_version_id'], ['bill_template_versions.id'], name='fk_bill_templates_active_version', ondelete='SET NULL', use_alter=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_bill_templates_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bill_templates'))
    )
    op.create_index('ux_bill_templates_name', 'bill_templates', [sa.literal_column('lower(name)')], unique=True)
    op.create_table('bill_template_versions',
    sa.Column('template_id', sa.UUID(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('formula', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_published', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.CheckConstraint('version_number > 0', name=op.f('ck_bill_template_versions_version_positive')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_bill_template_versions_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['template_id'], ['bill_templates.id'], name=op.f('fk_bill_template_versions_template_id_bill_templates'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bill_template_versions')),
    sa.UniqueConstraint('template_id', 'version_number', name='template_version')
    )
    op.create_index('ix_bill_template_versions_template', 'bill_template_versions', ['template_id', 'version_number'], unique=False)
    op.create_table('billing_runs',
    sa.Column('template_id', sa.UUID(), nullable=False),
    sa.Column('template_version_id', sa.UUID(), nullable=False),
    sa.Column('frequency', postgresql.ENUM('MONTHLY', 'QUARTERLY', 'HALF_YEARLY', 'YEARLY', 'ONE_TIME',
                    name='billing_frequency', create_type=False), nullable=False),
    sa.Column('period_key', sa.String(length=20), nullable=False),
    sa.Column('period_label', sa.String(length=60), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'RUNNING', 'COMPLETED', 'COMPLETED_WITH_ERRORS', 'FAILED', 'PUBLISHED', name='billing_run_status'), server_default='PENDING', nullable=False),
    sa.Column('total_flats', sa.Integer(), server_default='0', nullable=False),
    sa.Column('bills_generated', sa.Integer(), server_default='0', nullable=False),
    sa.Column('bills_failed', sa.Integer(), server_default='0', nullable=False),
    sa.Column('total_amount', sa.Numeric(precision=16, scale=2), server_default='0', nullable=False),
    sa.Column('error_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_by', sa.UUID(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('period_end >= period_start', name=op.f('ck_billing_runs_period_order')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_billing_runs_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['published_by'], ['users.id'], name=op.f('fk_billing_runs_published_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['template_id'], ['bill_templates.id'], name=op.f('fk_billing_runs_template_id_bill_templates'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['template_version_id'], ['bill_template_versions.id'], name=op.f('fk_billing_runs_template_version_id_bill_template_versions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_billing_runs'))
    )
    op.create_index('ix_billing_runs_status', 'billing_runs', ['status', 'created_at'], unique=False)
    op.create_index('ux_billing_runs_period', 'billing_runs', ['template_id', 'period_key'], unique=True, postgresql_where="status <> 'FAILED'")
    op.create_table('bill_template_assignments',
    sa.Column('template_id', sa.UUID(), nullable=False),
    sa.Column('scope', sa.Enum('ALL', 'BUILDING', 'BLOCK', 'FLAT_TYPE', 'FLAT', name='assignment_scope'), nullable=False),
    sa.Column('building_id', sa.UUID(), nullable=True),
    sa.Column('block_id', sa.UUID(), nullable=True),
    sa.Column('flat_id', sa.UUID(), nullable=True),
    sa.Column('flat_type', sa.String(length=20), nullable=True),
    sa.Column('priority', sa.Integer(), server_default='0', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(scope = 'ALL'      AND building_id IS NULL AND block_id IS NULL AND flat_id IS NULL AND flat_type IS NULL) OR (scope = 'BUILDING' AND building_id IS NOT NULL AND block_id IS NULL AND flat_id IS NULL) OR (scope = 'BLOCK'    AND block_id IS NOT NULL AND flat_id IS NULL) OR (scope = 'FLAT_TYPE'AND flat_type IS NOT NULL AND flat_id IS NULL) OR (scope = 'FLAT'     AND flat_id IS NOT NULL)", name=op.f('ck_bill_template_assignments_scope_target')),
    sa.ForeignKeyConstraint(['block_id'], ['blocks.id'], name=op.f('fk_bill_template_assignments_block_id_blocks'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['building_id'], ['buildings.id'], name=op.f('fk_bill_template_assignments_building_id_buildings'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['flat_id'], ['flats.id'], name=op.f('fk_bill_template_assignments_flat_id_flats'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['template_id'], ['bill_templates.id'], name=op.f('fk_bill_template_assignments_template_id_bill_templates'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bill_template_assignments'))
    )
    op.create_index('ix_assignments_flat', 'bill_template_assignments', ['flat_id'], unique=False, postgresql_where='flat_id IS NOT NULL')
    op.create_index('ix_assignments_template', 'bill_template_assignments', ['template_id'], unique=False, postgresql_where='is_active')
    op.create_table('maintenance_bills',
    sa.Column('bill_number', sa.String(length=40), nullable=False),
    sa.Column('billing_run_id', sa.UUID(), nullable=False),
    sa.Column('flat_id', sa.UUID(), nullable=False),
    sa.Column('template_id', sa.UUID(), nullable=False),
    sa.Column('template_version_id', sa.UUID(), nullable=False),
    sa.Column('formula_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('input_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('calculation_trace', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('period_key', sa.String(length=20), nullable=False),
    sa.Column('period_label', sa.String(length=60), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('subtotal', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
    sa.Column('penalty', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
    sa.Column('discount', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
    sa.Column('tax', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
    sa.Column('total', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
    sa.Column('amount_paid', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
    sa.Column('status', sa.Enum('DRAFT', 'PUBLISHED', 'FAILED', 'VOID', name='bill_status'), server_default='DRAFT', nullable=False),
    sa.Column('payment_status', sa.Enum('UNPAID', 'PARTIAL', 'PAID', 'OVERDUE', 'PENDING', 'SUCCESS', 'FAILED', 'REFUNDED', name='payment_status'), server_default='UNPAID', nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount_paid >= 0', name=op.f('ck_maintenance_bills_paid_non_negative')),
    sa.CheckConstraint('total >= 0', name=op.f('ck_maintenance_bills_total_non_negative')),
    sa.ForeignKeyConstraint(['billing_run_id'], ['billing_runs.id'], name=op.f('fk_maintenance_bills_billing_run_id_billing_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['flat_id'], ['flats.id'], name=op.f('fk_maintenance_bills_flat_id_flats'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['template_id'], ['bill_templates.id'], name=op.f('fk_maintenance_bills_template_id_bill_templates'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['template_version_id'], ['bill_template_versions.id'], name=op.f('fk_maintenance_bills_template_version_id_bill_template_versions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_maintenance_bills')),
    sa.UniqueConstraint('bill_number', name=op.f('uq_maintenance_bills_bill_number'))
    )
    op.create_index('ix_bills_due', 'maintenance_bills', ['due_date'], unique=False, postgresql_where="payment_status IN ('UNPAID','PARTIAL','OVERDUE')")
    op.create_index('ix_bills_flat', 'maintenance_bills', ['flat_id', 'period_start'], unique=False)
    op.create_index('ix_bills_run', 'maintenance_bills', ['billing_run_id'], unique=False)
    op.create_index('ix_bills_status', 'maintenance_bills', ['status', 'payment_status'], unique=False)
    op.create_index('ux_bills_flat_period', 'maintenance_bills', ['flat_id', 'template_id', 'period_key'], unique=True, postgresql_where="status <> 'VOID'")
    op.create_table('bill_line_items',
    sa.Column('bill_id', sa.UUID(), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('label', sa.String(length=80), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=True),
    sa.Column('unit', sa.String(length=12), nullable=True),
    sa.Column('rate', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('is_credit', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['bill_id'], ['maintenance_bills.id'], name=op.f('fk_bill_line_items_bill_id_maintenance_bills'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bill_line_items'))
    )
    op.create_index('ix_line_items_bill', 'bill_line_items', ['bill_id', 'sort_order'], unique=False)
    op.create_table('payments',
    sa.Column('bill_id', sa.UUID(), nullable=True),
    sa.Column('flat_id', sa.UUID(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('method', sa.Enum('CASH', 'CHEQUE', 'NEFT', 'UPI', 'CARD', 'NETBANKING', 'ADJUSTMENT', name='payment_method'), nullable=False),
    sa.Column('status', sa.Enum('UNPAID', 'PARTIAL', 'PAID', 'OVERDUE', 'PENDING', 'SUCCESS', 'FAILED', 'REFUNDED', name='payment_status'), server_default='PENDING', nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=True),
    sa.Column('provider_payment_id', sa.String(length=120), nullable=True),
    sa.Column('provider_order_id', sa.String(length=120), nullable=True),
    sa.Column('provider_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('reference_number', sa.String(length=80), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('recorded_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount > 0', name=op.f('ck_payments_amount_positive')),
    sa.ForeignKeyConstraint(['bill_id'], ['maintenance_bills.id'], name=op.f('fk_payments_bill_id_maintenance_bills'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['flat_id'], ['flats.id'], name=op.f('fk_payments_flat_id_flats'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], name=op.f('fk_payments_recorded_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payments'))
    )
    op.create_index('ix_payments_bill', 'payments', ['bill_id'], unique=False)
    op.create_index('ix_payments_flat', 'payments', ['flat_id', 'paid_at'], unique=False)
    op.create_index('ux_payments_provider', 'payments', ['provider', 'provider_payment_id'], unique=True, postgresql_where='provider_payment_id IS NOT NULL')
    # ### end Alembic commands ###

    # ------------------------------------------------------------------ #
    # Immutability. This is a financial record, so it is enforced by the
    # database rather than by a convention a future contributor can miss.
    # ------------------------------------------------------------------ #

    # A published template version never changes. Raising a rate creates v2;
    # every bill already generated still points at v1 and still carries v1's
    # frozen formula.
    op.execute(TEMPLATE_VERSION_IMMUTABLE_FN)
    op.execute(TEMPLATE_VERSION_IMMUTABLE_TRG)
    op.execute(TEMPLATE_VERSION_NO_DELETE_FN)
    op.execute(TEMPLATE_VERSION_NO_DELETE_TRG)

    # A published bill is immutable except for payment tracking. A wrong bill
    # is corrected with a credit note, never an edit.
    op.execute(BILL_GUARD_FN)
    op.execute(BILL_GUARD_TRG)
    op.execute(BILL_NO_DELETE_FN)
    op.execute(BILL_NO_DELETE_TRG)

    # Line items are part of the published record.
    op.execute(LINE_ITEM_GUARD_FN)
    op.execute(LINE_ITEM_GUARD_TRG)


def downgrade() -> None:
    for stmt in (
        "DROP TRIGGER IF EXISTS trg_line_item_guard ON bill_line_items",
        "DROP FUNCTION IF EXISTS nf_line_item_guard()",
        "DROP TRIGGER IF EXISTS trg_bill_no_delete ON maintenance_bills",
        "DROP FUNCTION IF EXISTS nf_bill_no_delete()",
        "DROP TRIGGER IF EXISTS trg_bill_guard ON maintenance_bills",
        "DROP FUNCTION IF EXISTS nf_bill_guard()",
        "DROP TRIGGER IF EXISTS trg_template_version_no_delete ON bill_template_versions",
        "DROP FUNCTION IF EXISTS nf_template_version_no_delete()",
        "DROP TRIGGER IF EXISTS trg_template_version_immutable ON bill_template_versions",
        "DROP FUNCTION IF EXISTS nf_template_version_immutable()",
    ):
        op.execute(stmt)

    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ux_payments_provider', table_name='payments', postgresql_where='provider_payment_id IS NOT NULL')
    op.drop_index('ix_payments_flat', table_name='payments')
    op.drop_index('ix_payments_bill', table_name='payments')
    op.drop_table('payments')
    op.drop_index('ix_line_items_bill', table_name='bill_line_items')
    op.drop_table('bill_line_items')
    op.drop_index('ux_bills_flat_period', table_name='maintenance_bills', postgresql_where="status <> 'VOID'")
    op.drop_index('ix_bills_status', table_name='maintenance_bills')
    op.drop_index('ix_bills_run', table_name='maintenance_bills')
    op.drop_index('ix_bills_flat', table_name='maintenance_bills')
    op.drop_index('ix_bills_due', table_name='maintenance_bills', postgresql_where="payment_status IN ('UNPAID','PARTIAL','OVERDUE')")
    op.drop_table('maintenance_bills')
    op.drop_index('ix_assignments_template', table_name='bill_template_assignments', postgresql_where='is_active')
    op.drop_index('ix_assignments_flat', table_name='bill_template_assignments', postgresql_where='flat_id IS NOT NULL')
    op.drop_table('bill_template_assignments')
    op.drop_index('ux_billing_runs_period', table_name='billing_runs', postgresql_where="status <> 'FAILED'")
    op.drop_index('ix_billing_runs_status', table_name='billing_runs')
    op.drop_table('billing_runs')
    op.drop_index('ix_bill_template_versions_template', table_name='bill_template_versions')
    op.drop_table('bill_template_versions')
    op.drop_index('ux_bill_templates_name', table_name='bill_templates')
    op.drop_table('bill_templates')
    # ### end Alembic commands ###

    # Native enum types outlive their tables, so a downgrade that leaves them
    # behind makes the next upgrade fail with "type already exists".
    # billing_frequency is NOT dropped: it was created by the Phase 1
    # migration for society_settings and is still in use there.
    for enum_name in (
        "assignment_scope",
        "bill_status",
        "billing_run_status",
        "payment_method",
        "payment_status",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")

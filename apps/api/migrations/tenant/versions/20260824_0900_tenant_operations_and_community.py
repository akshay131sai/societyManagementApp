"""tenant operations and community

Phase 5: complaints, work schedules and tasks, visitors, security incidents,
notices and amenity bookings.

Three things here are not ordinary ``create_table`` output and are written by
hand for reasons worth recording:

* ``btree_gist`` is created first. The amenity booking exclusion constraint
  compares a UUID for equality *and* a range for overlap in one GiST index, and
  the UUID half needs that extension.

* ``complaint_ticket_seq`` backs the ``ticket_number`` default. Handing out the
  number in the database is what makes two simultaneous submissions safe
  without a lock.

* The ``tstzrange`` exclusion constraint is emitted as raw SQL. Alembic can
  render it, but the generated form loses the ``WHERE`` clause that lets a
  cancelled booking release its slot — and that clause is the difference
  between a working calendar and a permanently blocked clubhouse.

Revision ID: 8a41f2c9d05e
Revises: d1653b8857c4
Create Date: 2026-08-24 09:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '8a41f2c9d05e'
down_revision: str | None = 'd1653b8857c4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PRIORITY = ('LOW', 'MEDIUM', 'HIGH', 'URGENT')
COMPLAINT_CATEGORY = (
    'PLUMBING', 'ELECTRICAL', 'LIFT', 'HOUSEKEEPING', 'SECURITY', 'PARKING',
    'NOISE', 'WATER_SUPPLY', 'COMMON_AREA', 'BILLING', 'OTHER',
)
COMPLAINT_STATUS = (
    'OPEN', 'ACKNOWLEDGED', 'IN_PROGRESS', 'RESOLVED', 'CLOSED', 'REJECTED', 'REOPENED',
)
DEPARTMENT = ('MAINTENANCE', 'HOUSEKEEPING')
TASK_STATUS = ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'VERIFIED', 'CANCELLED', 'SKIPPED')
RECURRENCE = (
    'DAILY', 'WEEKLY', 'FORTNIGHTLY', 'MONTHLY', 'QUARTERLY', 'HALF_YEARLY', 'YEARLY',
)
VISITOR_TYPE = ('GUEST', 'DELIVERY', 'CAB', 'SERVICE', 'DOMESTIC_HELP', 'VENDOR', 'OTHER')
VISITOR_STATUS = (
    'EXPECTED', 'AWAITING_APPROVAL', 'APPROVED', 'DENIED', 'CHECKED_IN',
    'CHECKED_OUT', 'EXPIRED',
)
INCIDENT_SEVERITY = ('INFO', 'MINOR', 'MAJOR', 'CRITICAL')
INCIDENT_STATUS = ('REPORTED', 'INVESTIGATING', 'RESOLVED', 'CLOSED')
NOTICE_CATEGORY = (
    'GENERAL', 'URGENT', 'MAINTENANCE', 'EVENT', 'MEETING', 'BILLING', 'SECURITY',
)
AUDIENCE_SCOPE = ('ALL', 'BUILDING', 'BLOCK', 'OWNERS', 'TENANTS', 'STAFF')
BOOKING_STATUS = (
    'PENDING', 'CONFIRMED', 'CANCELLED', 'REJECTED', 'COMPLETED', 'NO_SHOW',
)

TICKET_DEFAULT = (
    "'CMP-' || to_char(now() AT TIME ZONE 'Asia/Kolkata', 'YYYY') || '-' || "
    "lpad(nextval('complaint_ticket_seq')::text, 5, '0')"
)

OPEN_COMPLAINTS = "status IN ('OPEN', 'ACKNOWLEDGED', 'IN_PROGRESS', 'REOPENED')"
OPEN_TASKS = "status IN ('PENDING', 'IN_PROGRESS')"
LIVE_PASSES = (
    "pass_code IS NOT NULL AND status IN "
    "('EXPECTED', 'AWAITING_APPROVAL', 'APPROVED', 'CHECKED_IN')"
)
BOOKING_HOLDS_SLOT = "status IN ('PENDING', 'CONFIRMED')"


def _enum(name: str, values: Sequence[str]) -> postgresql.ENUM:
    # create_type=False: the types are created once, up front, so a table that
    # uses one twice does not try to create it twice.
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute('CREATE EXTENSION IF NOT EXISTS btree_gist')
    op.execute('CREATE SEQUENCE IF NOT EXISTS complaint_ticket_seq START 1')

    for name, values in (
        ('priority', PRIORITY),
        ('complaint_category', COMPLAINT_CATEGORY),
        ('complaint_status', COMPLAINT_STATUS),
        ('department', DEPARTMENT),
        ('task_status', TASK_STATUS),
        ('recurrence', RECURRENCE),
        ('visitor_type', VISITOR_TYPE),
        ('visitor_status', VISITOR_STATUS),
        ('incident_severity', INCIDENT_SEVERITY),
        ('incident_status', INCIDENT_STATUS),
        ('notice_category', NOTICE_CATEGORY),
        ('audience_scope', AUDIENCE_SCOPE),
        ('booking_status', BOOKING_STATUS),
    ):
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    # ----------------------------------------------------------------- #
    # Complaints
    # ----------------------------------------------------------------- #

    op.create_table(
        'complaints',
        sa.Column('ticket_number', sa.String(length=20), server_default=sa.text(TICKET_DEFAULT), nullable=False),
        sa.Column('flat_id', sa.UUID(), nullable=True),
        sa.Column('raised_by', sa.UUID(), nullable=True),
        sa.Column('raised_by_name', sa.String(length=150), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', _enum('complaint_category', COMPLAINT_CATEGORY), server_default='OTHER', nullable=False),
        sa.Column('priority', _enum('priority', PRIORITY), server_default='MEDIUM', nullable=False),
        sa.Column('status', _enum('complaint_status', COMPLAINT_STATUS), server_default='OPEN', nullable=False),
        sa.Column('location', sa.String(length=200), nullable=True),
        sa.Column('assigned_to', sa.UUID(), nullable=True),
        sa.Column('assigned_department', _enum('department', DEPARTMENT), nullable=True),
        sa.Column('due_by', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('reopen_count', sa.SmallInteger(), server_default='0', nullable=False),
        sa.Column('rating', sa.SmallInteger(), nullable=True),
        sa.Column('rating_comment', sa.Text(), nullable=True),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('rating IS NULL OR rating BETWEEN 1 AND 5', name=op.f('ck_complaints_rating_range')),
        sa.CheckConstraint('reopen_count >= 0', name=op.f('ck_complaints_reopen_count_non_negative')),
        sa.CheckConstraint('resolved_at IS NULL OR resolved_at >= created_at', name=op.f('ck_complaints_resolved_after_raised')),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], name=op.f('fk_complaints_assigned_to_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['flat_id'], ['flats.id'], name=op.f('fk_complaints_flat_id_flats'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['raised_by'], ['users.id'], name=op.f('fk_complaints_raised_by_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_complaints')),
        sa.UniqueConstraint('ticket_number', name=op.f('uq_complaints_ticket_number')),
    )
    op.create_index('ix_complaints_assignee', 'complaints', ['assigned_to'], unique=False, postgresql_where='assigned_to IS NOT NULL')
    op.create_index('ix_complaints_category', 'complaints', ['category', 'created_at'], unique=False)
    op.create_index('ix_complaints_flat', 'complaints', ['flat_id'], unique=False, postgresql_where='flat_id IS NOT NULL')
    op.create_index('ix_complaints_open_due', 'complaints', ['due_by'], unique=False, postgresql_where=OPEN_COMPLAINTS)
    op.create_index('ix_complaints_status', 'complaints', ['status', 'created_at'], unique=False)

    op.create_table(
        'complaint_comments',
        sa.Column('complaint_id', sa.UUID(), nullable=False),
        sa.Column('author_id', sa.UUID(), nullable=True),
        sa.Column('author_name', sa.String(length=150), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('is_internal', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('is_system', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_complaint_comments_author_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], name=op.f('fk_complaint_comments_complaint_id_complaints'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_complaint_comments')),
    )
    op.create_index('ix_complaint_comments_complaint', 'complaint_comments', ['complaint_id', 'created_at'], unique=False)

    # ----------------------------------------------------------------- #
    # Work schedules and tasks
    # ----------------------------------------------------------------- #

    op.create_table(
        'work_schedules',
        sa.Column('department', _enum('department', DEPARTMENT), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('area', sa.String(length=200), nullable=True),
        sa.Column('building_id', sa.UUID(), nullable=True),
        sa.Column('recurrence', _enum('recurrence', RECURRENCE), nullable=False),
        sa.Column('priority', _enum('priority', PRIORITY), server_default='MEDIUM', nullable=False),
        sa.Column('assigned_to', sa.UUID(), nullable=True),
        sa.Column('estimated_cost', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('vendor_name', sa.String(length=150), nullable=True),
        sa.Column('vendor_phone', sa.String(length=10), nullable=True),
        sa.Column('starts_on', sa.Date(), nullable=False),
        sa.Column('next_due_on', sa.Date(), nullable=False),
        sa.Column('ends_on', sa.Date(), nullable=True),
        sa.Column('lead_days', sa.SmallInteger(), server_default='3', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('estimated_cost IS NULL OR estimated_cost >= 0', name=op.f('ck_work_schedules_cost_non_negative')),
        sa.CheckConstraint('lead_days BETWEEN 0 AND 90', name=op.f('ck_work_schedules_lead_days_range')),
        sa.CheckConstraint('ends_on IS NULL OR ends_on >= starts_on', name=op.f('ck_work_schedules_date_order')),
        sa.CheckConstraint("vendor_phone IS NULL OR vendor_phone ~ '^[6-9][0-9]{9}$'", name=op.f('ck_work_schedules_phone_format')),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], name=op.f('fk_work_schedules_assigned_to_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['building_id'], ['buildings.id'], name=op.f('fk_work_schedules_building_id_buildings'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_work_schedules')),
    )
    op.create_index('ix_work_schedules_department', 'work_schedules', ['department', 'next_due_on'], unique=False)
    op.create_index('ix_work_schedules_due', 'work_schedules', ['next_due_on'], unique=False, postgresql_where='is_active')

    op.create_table(
        'work_tasks',
        sa.Column('department', _enum('department', DEPARTMENT), nullable=False),
        sa.Column('schedule_id', sa.UUID(), nullable=True),
        sa.Column('complaint_id', sa.UUID(), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('area', sa.String(length=200), nullable=True),
        sa.Column('building_id', sa.UUID(), nullable=True),
        sa.Column('status', _enum('task_status', TASK_STATUS), server_default='PENDING', nullable=False),
        sa.Column('priority', _enum('priority', PRIORITY), server_default='MEDIUM', nullable=False),
        sa.Column('assigned_to', sa.UUID(), nullable=True),
        sa.Column('due_on', sa.Date(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_by', sa.UUID(), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verified_by', sa.UUID(), nullable=True),
        sa.Column('completion_notes', sa.Text(), nullable=True),
        sa.Column('actual_cost', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('vendor_name', sa.String(length=150), nullable=True),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('actual_cost IS NULL OR actual_cost >= 0', name=op.f('ck_work_tasks_cost_non_negative')),
        sa.CheckConstraint('completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at', name=op.f('ck_work_tasks_completed_after_started')),
        sa.CheckConstraint('verified_at IS NULL OR completed_at IS NOT NULL', name=op.f('ck_work_tasks_verified_implies_completed')),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], name=op.f('fk_work_tasks_assigned_to_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['building_id'], ['buildings.id'], name=op.f('fk_work_tasks_building_id_buildings'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], name=op.f('fk_work_tasks_complaint_id_complaints'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['completed_by'], ['users.id'], name=op.f('fk_work_tasks_completed_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['schedule_id'], ['work_schedules.id'], name=op.f('fk_work_tasks_schedule_id_work_schedules'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['verified_by'], ['users.id'], name=op.f('fk_work_tasks_verified_by_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_work_tasks')),
    )
    op.create_index('ix_work_tasks_assignee', 'work_tasks', ['assigned_to', 'status'], unique=False, postgresql_where='assigned_to IS NOT NULL')
    op.create_index('ix_work_tasks_complaint', 'work_tasks', ['complaint_id'], unique=False, postgresql_where='complaint_id IS NOT NULL')
    op.create_index('ix_work_tasks_department', 'work_tasks', ['department', 'due_on'], unique=False)
    op.create_index('ix_work_tasks_open', 'work_tasks', ['due_on'], unique=False, postgresql_where=OPEN_TASKS)
    op.create_index('ux_work_tasks_occurrence', 'work_tasks', ['schedule_id', 'due_on'], unique=True, postgresql_where='schedule_id IS NOT NULL')

    # ----------------------------------------------------------------- #
    # Visitors
    # ----------------------------------------------------------------- #

    op.create_table(
        'visitors',
        sa.Column('pass_code', sa.String(length=8), nullable=True),
        sa.Column('flat_id', sa.UUID(), nullable=False),
        sa.Column('visitor_name', sa.String(length=150), nullable=False),
        sa.Column('visitor_phone', sa.String(length=10), nullable=True),
        sa.Column('visitor_type', _enum('visitor_type', VISITOR_TYPE), server_default='GUEST', nullable=False),
        sa.Column('company', sa.String(length=120), nullable=True),
        sa.Column('purpose', sa.String(length=300), nullable=True),
        sa.Column('accompanying_count', sa.SmallInteger(), server_default='0', nullable=False),
        sa.Column('vehicle_number', sa.String(length=20), nullable=True),
        sa.Column('status', _enum('visitor_status', VISITOR_STATUS), server_default='AWAITING_APPROVAL', nullable=False),
        sa.Column('expected_from', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expected_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.UUID(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('denial_reason', sa.String(length=300), nullable=True),
        sa.Column('checked_in_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('checked_in_by', sa.UUID(), nullable=True),
        sa.Column('checked_out_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('checked_out_by', sa.UUID(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("visitor_phone IS NULL OR visitor_phone ~ '^[6-9][0-9]{9}$'", name=op.f('ck_visitors_phone_format')),
        sa.CheckConstraint('accompanying_count BETWEEN 0 AND 50', name=op.f('ck_visitors_accompanying_count_range')),
        sa.CheckConstraint('expected_to IS NULL OR expected_from IS NULL OR expected_to >= expected_from', name=op.f('ck_visitors_window_order')),
        sa.CheckConstraint('checked_out_at IS NULL OR checked_in_at IS NOT NULL', name=op.f('ck_visitors_checkout_implies_checkin')),
        sa.CheckConstraint('checked_out_at IS NULL OR checked_out_at >= checked_in_at', name=op.f('ck_visitors_checkout_after_checkin')),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], name=op.f('fk_visitors_approved_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['checked_in_by'], ['users.id'], name=op.f('fk_visitors_checked_in_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['checked_out_by'], ['users.id'], name=op.f('fk_visitors_checked_out_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['flat_id'], ['flats.id'], name=op.f('fk_visitors_flat_id_flats'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_visitors')),
    )
    op.create_index('ix_visitors_expected', 'visitors', ['expected_from'], unique=False, postgresql_where="status IN ('EXPECTED', 'APPROVED')")
    op.create_index('ix_visitors_flat', 'visitors', ['flat_id', 'created_at'], unique=False)
    op.create_index('ix_visitors_on_premises', 'visitors', ['checked_in_at'], unique=False, postgresql_where="status = 'CHECKED_IN'")
    op.create_index('ix_visitors_status', 'visitors', ['status', 'created_at'], unique=False)
    op.create_index('ux_visitors_pass_code', 'visitors', ['pass_code'], unique=True, postgresql_where=LIVE_PASSES)

    # ----------------------------------------------------------------- #
    # Security incidents
    # ----------------------------------------------------------------- #

    op.create_table(
        'security_incidents',
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('severity', _enum('incident_severity', INCIDENT_SEVERITY), server_default='MINOR', nullable=False),
        sa.Column('status', _enum('incident_status', INCIDENT_STATUS), server_default='REPORTED', nullable=False),
        sa.Column('location', sa.String(length=200), nullable=True),
        sa.Column('building_id', sa.UUID(), nullable=True),
        sa.Column('flat_id', sa.UUID(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reported_by', sa.UUID(), nullable=True),
        sa.Column('reported_by_name', sa.String(length=150), nullable=False),
        sa.Column('action_taken', sa.Text(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('police_reference', sa.String(length=60), nullable=True),
        sa.Column('people_involved', sa.Integer(), nullable=True),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('people_involved IS NULL OR people_involved >= 0', name=op.f('ck_security_incidents_people_non_negative')),
        sa.CheckConstraint('resolved_at IS NULL OR resolved_at >= occurred_at', name=op.f('ck_security_incidents_resolved_after_occurred')),
        sa.ForeignKeyConstraint(['building_id'], ['buildings.id'], name=op.f('fk_security_incidents_building_id_buildings'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['flat_id'], ['flats.id'], name=op.f('fk_security_incidents_flat_id_flats'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reported_by'], ['users.id'], name=op.f('fk_security_incidents_reported_by_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_security_incidents')),
    )
    op.create_index('ix_incidents_occurred', 'security_incidents', ['occurred_at'], unique=False)
    op.create_index('ix_incidents_open', 'security_incidents', ['severity'], unique=False, postgresql_where="status IN ('REPORTED', 'INVESTIGATING')")
    op.create_index('ix_incidents_status', 'security_incidents', ['status', 'occurred_at'], unique=False)

    # ----------------------------------------------------------------- #
    # Notices
    # ----------------------------------------------------------------- #

    op.create_table(
        'notices',
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('category', _enum('notice_category', NOTICE_CATEGORY), server_default='GENERAL', nullable=False),
        sa.Column('priority', _enum('priority', PRIORITY), server_default='MEDIUM', nullable=False),
        sa.Column('audience', _enum('audience_scope', AUDIENCE_SCOPE), server_default='ALL', nullable=False),
        sa.Column('building_id', sa.UUID(), nullable=True),
        sa.Column('block_id', sa.UUID(), nullable=True),
        sa.Column('is_pinned', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('is_published', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('publish_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attachments', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('author_id', sa.UUID(), nullable=True),
        sa.Column('author_name', sa.String(length=150), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('expires_at IS NULL OR publish_at IS NULL OR expires_at > publish_at', name=op.f('ck_notices_window_order')),
        sa.CheckConstraint(
            "(audience <> 'BUILDING' OR building_id IS NOT NULL) AND "
            "(audience <> 'BLOCK' OR block_id IS NOT NULL)",
            name=op.f('ck_notices_audience_target_present'),
        ),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_notices_author_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['block_id'], ['blocks.id'], name=op.f('fk_notices_block_id_blocks'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['building_id'], ['buildings.id'], name=op.f('fk_notices_building_id_buildings'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_notices')),
    )
    op.create_index('ix_notices_category', 'notices', ['category', 'created_at'], unique=False)
    op.create_index('ix_notices_pinned', 'notices', ['is_pinned', 'publish_at'], unique=False, postgresql_where='is_published')
    op.create_index('ix_notices_published', 'notices', ['publish_at'], unique=False, postgresql_where='is_published')

    op.create_table(
        'notice_reads',
        sa.Column('notice_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.ForeignKeyConstraint(['notice_id'], ['notices.id'], name=op.f('fk_notice_reads_notice_id_notices'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notice_reads_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_notice_reads')),
        sa.UniqueConstraint('notice_id', 'user_id', name='notice_user'),
    )
    op.create_index('ix_notice_reads_user', 'notice_reads', ['user_id'], unique=False)

    # ----------------------------------------------------------------- #
    # Amenities
    # ----------------------------------------------------------------- #

    op.create_table(
        'amenities',
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('location', sa.String(length=200), nullable=True),
        sa.Column('building_id', sa.UUID(), nullable=True),
        sa.Column('capacity', sa.SmallInteger(), nullable=True),
        sa.Column('opens_at', sa.Time(), nullable=False),
        sa.Column('closes_at', sa.Time(), nullable=False),
        sa.Column('slot_minutes', sa.SmallInteger(), server_default='60', nullable=False),
        sa.Column('booking_charge', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
        sa.Column('max_advance_days', sa.SmallInteger(), server_default='30', nullable=False),
        sa.Column('max_slots_per_booking', sa.SmallInteger(), server_default='2', nullable=False),
        sa.Column('max_active_per_flat', sa.SmallInteger(), server_default='3', nullable=False),
        sa.Column('requires_approval', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('rules', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('closes_at > opens_at', name=op.f('ck_amenities_hours_order')),
        sa.CheckConstraint('slot_minutes BETWEEN 15 AND 1440', name=op.f('ck_amenities_slot_minutes_range')),
        sa.CheckConstraint('booking_charge >= 0', name=op.f('ck_amenities_charge_non_negative')),
        sa.CheckConstraint('max_advance_days BETWEEN 1 AND 365', name=op.f('ck_amenities_advance_days_range')),
        sa.CheckConstraint('max_slots_per_booking BETWEEN 1 AND 48', name=op.f('ck_amenities_slots_per_booking_range')),
        sa.CheckConstraint('max_active_per_flat BETWEEN 1 AND 50', name=op.f('ck_amenities_active_per_flat_range')),
        sa.CheckConstraint('capacity IS NULL OR capacity > 0', name=op.f('ck_amenities_capacity_positive')),
        sa.ForeignKeyConstraint(['building_id'], ['buildings.id'], name=op.f('fk_amenities_building_id_buildings'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_amenities')),
    )
    op.create_index('ix_amenities_active', 'amenities', ['name'], unique=False, postgresql_where='is_active')
    op.create_index('ux_amenities_name', 'amenities', [sa.literal_column('lower(name)')], unique=True)

    op.create_table(
        'amenity_bookings',
        sa.Column('amenity_id', sa.UUID(), nullable=False),
        sa.Column('flat_id', sa.UUID(), nullable=False),
        sa.Column('booked_by', sa.UUID(), nullable=True),
        sa.Column('booked_by_name', sa.String(length=150), nullable=False),
        sa.Column('booking_date', sa.Date(), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('slots', sa.SmallInteger(), server_default='1', nullable=False),
        sa.Column('guests', sa.SmallInteger(), server_default='0', nullable=False),
        sa.Column('purpose', sa.String(length=300), nullable=True),
        sa.Column('status', _enum('booking_status', BOOKING_STATUS), server_default='CONFIRMED', nullable=False),
        sa.Column('charge', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
        sa.Column('approved_by', sa.UUID(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancellation_reason', sa.String(length=300), nullable=True),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('ends_at > starts_at', name=op.f('ck_amenity_bookings_window_order')),
        sa.CheckConstraint('slots BETWEEN 1 AND 48', name=op.f('ck_amenity_bookings_slots_range')),
        sa.CheckConstraint('guests BETWEEN 0 AND 500', name=op.f('ck_amenity_bookings_guests_range')),
        sa.CheckConstraint('charge >= 0', name=op.f('ck_amenity_bookings_charge_non_negative')),
        sa.ForeignKeyConstraint(['amenity_id'], ['amenities.id'], name=op.f('fk_amenity_bookings_amenity_id_amenities'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], name=op.f('fk_amenity_bookings_approved_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['booked_by'], ['users.id'], name=op.f('fk_amenity_bookings_booked_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['flat_id'], ['flats.id'], name=op.f('fk_amenity_bookings_flat_id_flats'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_amenity_bookings')),
    )
    op.create_index('ix_bookings_amenity_date', 'amenity_bookings', ['amenity_id', 'booking_date'], unique=False)
    op.create_index('ix_bookings_flat', 'amenity_bookings', ['flat_id', 'starts_at'], unique=False)
    op.create_index('ix_bookings_upcoming', 'amenity_bookings', ['starts_at'], unique=False, postgresql_where=BOOKING_HOLDS_SLOT)

    # The double-booking guarantee. Two residents pressing Book on the same
    # 9 a.m. Sunday slot is not a rare case; an application-level "check then
    # insert" loses that race, and this does not.
    op.execute(
        'ALTER TABLE amenity_bookings ADD CONSTRAINT no_overlapping_bookings '
        'EXCLUDE USING gist ('
        'amenity_id WITH =, tstzrange(starts_at, ends_at, \'[)\') WITH &&'
        f') WHERE ({BOOKING_HOLDS_SLOT})'
    )


def downgrade() -> None:
    op.execute('ALTER TABLE amenity_bookings DROP CONSTRAINT IF EXISTS no_overlapping_bookings')

    for table in (
        'amenity_bookings',
        'amenities',
        'notice_reads',
        'notices',
        'security_incidents',
        'visitors',
        'work_tasks',
        'work_schedules',
        'complaint_comments',
        'complaints',
    ):
        op.drop_table(table)

    op.execute('DROP SEQUENCE IF EXISTS complaint_ticket_seq')

    bind = op.get_bind()
    for name in (
        'booking_status',
        'audience_scope',
        'notice_category',
        'incident_status',
        'incident_severity',
        'visitor_status',
        'visitor_type',
        'recurrence',
        'task_status',
        'department',
        'complaint_status',
        'complaint_category',
        'priority',
    ):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)

    # btree_gist is left in place: dropping an extension another migration or a
    # future index may depend on is a worse trade than leaving it installed.

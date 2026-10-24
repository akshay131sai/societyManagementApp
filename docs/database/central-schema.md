# Central Database Schema — `nestflow_platform`

> Platform-level data **only**. No residents, no bills, no vehicles, no visitors.
> If a table would have one row per flat, it belongs in a tenant database.

## 1. ERD

```
                          +---------------------+
                          |  subscription_plans |
                          +----------+----------+
                                     | 1
                                     |
                                     | N
+------------------+ 1     N +-------+---------+ 1     1 +--------------------+
|  platform_users  +---------+    subscriptions +---------+                    |
+--------+---------+         +-------+---------+         |                    |
         | N                         | N                 |                    |
         |                           |                   |                    |
         | 1                         | 1                 |                    |
+--------+---------------------------+-------------------+--------+           |
|                             societies                            |          |
+--------+-----------------------------------------+--------------+          |
         | 1                                       | 1                       |
         |                                         |                         |
         | N                                       | 1                       |
+--------+-------------------+          +----------+----------+              |
| society_admin_assignments  |          |  database_registry  |              |
+----------------------------+          +---------------------+              |
                                                                             |
+---------------------+                                                      |
| platform_audit_logs +------------------------------------------------------+
+---------------------+
```

## 2. Conventions

- Primary keys: `UUID` default `gen_random_uuid()` (pgcrypto/PG13+ builtin).
- Timestamps: `TIMESTAMPTZ`, always UTC. `created_at`, `updated_at` on every table.
- Enums: PostgreSQL native `ENUM` types — they are validated by the database and
  cheap; a `CHECK` on `TEXT` would not surface in the catalogue for tooling.
- Money: `NUMERIC(12,2)`. Never `float`.
- Soft delete: only where an audit trail demands it (`societies`, `platform_users`).
  Everything else deletes hard.

## 3. Enum types

```sql
CREATE TYPE society_status AS ENUM (
    'PROVISIONING', 'PROVISIONING_FAILED', 'ACTIVE',
    'LOCKED', 'SUSPENDED', 'ARCHIVED'
);

CREATE TYPE subscription_status AS ENUM (
    'TRIAL', 'ACTIVE', 'EXPIRED', 'CANCELLED', 'SUSPENDED'
);

CREATE TYPE billing_cycle AS ENUM (
    'MONTHLY', 'QUARTERLY', 'HALF_YEARLY', 'YEARLY'
);

CREATE TYPE provisioning_state AS ENUM (
    'PENDING', 'DATABASE_CREATED', 'MIGRATED', 'SEEDED', 'COMPLETED', 'FAILED'
);
```

`PROVISIONING_FAILED` is deliberately distinct from `SUSPENDED`: one is our
fault and needs an engineer, the other is a business decision.

## 4. Tables

### `societies`

The tenant root record.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | TEXT NOT NULL | "Green Valley Residency" |
| `slug` | TEXT NOT NULL UNIQUE | url-safe, immutable after creation |
| `registration_number` | TEXT | society registration no. |
| `address_line1` / `line2` | TEXT | |
| `city` / `state` | TEXT NOT NULL | |
| `pincode` | TEXT NOT NULL | `CHECK (pincode ~ '^[1-9][0-9]{5}$')` |
| `contact_email` | TEXT NOT NULL | |
| `contact_phone` | TEXT NOT NULL | `CHECK (~ '^[6-9][0-9]{9}$')` — Indian mobile |
| `timezone` | TEXT NOT NULL DEFAULT `'Asia/Kolkata'` | |
| `status` | `society_status` NOT NULL DEFAULT `'PROVISIONING'` | |
| `total_flats` | INT DEFAULT 0 | denormalised counter, refreshed by tenant events |
| `locked_at` / `locked_reason` | TIMESTAMPTZ / TEXT | |
| `archived_at` | TIMESTAMPTZ | |
| `created_by` | UUID FK -> platform_users | |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

```sql
CREATE UNIQUE INDEX ix_societies_slug ON societies (slug);
CREATE INDEX ix_societies_status ON societies (status) WHERE status <> 'ARCHIVED';
```

### `database_registry`

One row per society. The **only** place a tenant DSN is resolved from.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `society_id` | UUID FK UNIQUE NOT NULL | one database per society |
| `database_name` | TEXT NOT NULL UNIQUE | `CHECK (~ '^nestflow_society_[0-9]{4,10}$')` |
| `sequence_number` | INT NOT NULL UNIQUE | from `society_db_seq` |
| `host` / `port` | TEXT / INT NOT NULL | supports moving a tenant to another instance later |
| `provisioning_state` | `provisioning_state` NOT NULL DEFAULT `'PENDING'` | |
| `provisioning_error` | TEXT | populated on FAILED |
| `alembic_revision` | TEXT | tenant migration head actually applied |
| `migrated_at` | TIMESTAMPTZ | |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

Credentials are **not** stored here — they come from `TENANT_DB_USER` /
`TENANT_DB_PASSWORD` in the environment. A database dump therefore contains no
usable credentials.

```sql
CREATE SEQUENCE society_db_seq START 1;
CREATE UNIQUE INDEX ix_dbreg_society ON database_registry (society_id);
CREATE UNIQUE INDEX ix_dbreg_dbname  ON database_registry (database_name);
```

### `platform_users`

Every human who can authenticate, across all societies. This is the
`firebase_uid` -> society mapping, and therefore the hinge of tenant isolation.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `firebase_uid` | TEXT NOT NULL UNIQUE | from the verified ID token |
| `email` | TEXT NOT NULL | |
| `phone` | TEXT | |
| `display_name` | TEXT NOT NULL | |
| `is_super_admin` | BOOLEAN NOT NULL DEFAULT false | |
| `society_id` | UUID FK NULL | **NULL iff `is_super_admin`** |
| `tenant_user_id` | UUID NULL | id of the matching row in the tenant `users` table |
| `is_active` | BOOLEAN NOT NULL DEFAULT true | |
| `last_login_at` | TIMESTAMPTZ | |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

```sql
CREATE UNIQUE INDEX ix_pusers_firebase_uid ON platform_users (firebase_uid);
CREATE INDEX ix_pusers_email   ON platform_users (lower(email));
CREATE INDEX ix_pusers_society ON platform_users (society_id) WHERE society_id IS NOT NULL;

ALTER TABLE platform_users ADD CONSTRAINT ck_pusers_scope CHECK (
    (is_super_admin AND society_id IS NULL)
    OR (NOT is_super_admin AND society_id IS NOT NULL)
);
```

That `CHECK` is a real security control: it makes "a super admin who is also
scoped to a society" — the shape most tenant-escape bugs need — unrepresentable.

Email is intentionally **not** globally unique: the same person may be a
resident in two societies, which means two rows and two Firebase accounts.
`(society_id, lower(email))` is unique instead.

### `subscription_plans`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | TEXT NOT NULL UNIQUE | "Starter", "Growth", "Enterprise" |
| `code` | TEXT NOT NULL UNIQUE | machine key |
| `description` | TEXT | |
| `price` | NUMERIC(12,2) NOT NULL | INR |
| `billing_cycle` | `billing_cycle` NOT NULL | |
| `max_flats` | INT | NULL = unlimited |
| `max_users` | INT | NULL = unlimited |
| `features` | JSONB NOT NULL DEFAULT `'{}'` | feature flags |
| `trial_days` | INT NOT NULL DEFAULT 14 | |
| `is_active` | BOOLEAN NOT NULL DEFAULT true | |
| `sort_order` | INT NOT NULL DEFAULT 0 | |
| `created_at` / `updated_at` | | |

Plans are never hard-deleted — deactivated only, because subscriptions reference
them historically.

### `subscriptions`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `society_id` | UUID FK NOT NULL | |
| `plan_id` | UUID FK NOT NULL | |
| `status` | `subscription_status` NOT NULL | |
| `start_date` / `end_date` | DATE NOT NULL | |
| `is_current` | BOOLEAN NOT NULL DEFAULT true | |
| `price_snapshot` | NUMERIC(12,2) NOT NULL | plan price at assignment |
| `max_flats_snapshot` / `max_users_snapshot` | INT | limits at assignment |
| `cancelled_at` / `cancellation_reason` | | |
| `notes` | TEXT | |
| `created_by` | UUID FK -> platform_users | |
| `created_at` / `updated_at` | | |

```sql
-- exactly one current subscription per society
CREATE UNIQUE INDEX ux_subs_current ON subscriptions (society_id) WHERE is_current;
CREATE INDEX ix_subs_expiry ON subscriptions (end_date)
    WHERE is_current AND status IN ('TRIAL','ACTIVE');
ALTER TABLE subscriptions ADD CONSTRAINT ck_subs_dates CHECK (end_date >= start_date);
```

Limits are snapshotted so that raising a plan's `max_flats` does not
retroactively change what an existing subscriber was sold. Renewal/extension
appends a new row and flips `is_current`; history is preserved.

### `society_admin_assignments`

Tracks who administers which society, including revocation history. The *live*
mapping is `platform_users.society_id`; this table is the audit trail.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `society_id` | UUID FK NOT NULL | |
| `platform_user_id` | UUID FK NOT NULL | |
| `assigned_by` | UUID FK NOT NULL | |
| `assigned_at` | TIMESTAMPTZ NOT NULL | |
| `revoked_at` / `revoked_by` / `revoked_reason` | | |
| `is_active` | BOOLEAN NOT NULL DEFAULT true | |

```sql
CREATE UNIQUE INDEX ux_saa_active ON society_admin_assignments (society_id, platform_user_id)
    WHERE is_active;
```

### `platform_audit_logs`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | high volume; UUID not needed |
| `request_id` | TEXT | correlates to access logs |
| `action` | TEXT NOT NULL | `SOCIETY_LOCKED`, ... |
| `actor_id` | UUID FK NULL | NULL for system/scheduler |
| `actor_email` | TEXT | denormalised — survives user deletion |
| `society_id` | UUID FK NULL | |
| `target_type` / `target_id` | TEXT / TEXT | |
| `changes` | JSONB | `{before, after}` diff, secrets stripped |
| `ip_address` | INET | |
| `user_agent` | TEXT | |
| `status` | TEXT NOT NULL | `SUCCESS` / `FAILURE` |
| `created_at` | TIMESTAMPTZ NOT NULL | |

```sql
CREATE INDEX ix_paudit_created ON platform_audit_logs (created_at DESC);
CREATE INDEX ix_paudit_society ON platform_audit_logs (society_id, created_at DESC);
CREATE INDEX ix_paudit_actor   ON platform_audit_logs (actor_id, created_at DESC);
CREATE INDEX ix_paudit_action  ON platform_audit_logs (action, created_at DESC);
```

Append-only by convention now; a revoke of UPDATE/DELETE for the application
role is listed as a production hardening step in the deployment doc.

## 5. What must never appear here

`residents`, `flats`, `maintenance_bills`, `water_readings`, `vehicles`,
`visitors`, `complaints`, `payments`, `notices` — all tenant-scoped.

The only aggregate the central DB keeps is `societies.total_flats`, and only
because the Super Admin society list would otherwise need to fan out across
every tenant database to render one column.

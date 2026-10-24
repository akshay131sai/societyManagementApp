# Tenant Database Schema — `nestflow_society_NNNN`

> One database per society. Every table here is implicitly scoped to that
> society, so **no table carries a `society_id` column**. The database *is* the
> tenant boundary. Adding a `society_id` column here is a design error.

Phases 1 and 2 are built — the tables marked **[P1]** and **[P2]** exist. The
rest are specified now so the migration sequence and foreign keys are
planned, and are created in the phase noted.

## 1. Domain map

```
  IDENTITY & ACCESS  [P1]          PHYSICAL STRUCTURE  [P2]
  users                            buildings
  roles                              +-- blocks
  permissions                            +-- floors
  role_permissions                           +-- flats
  user_roles                                     +-- residents
                                                 +-- family_members
  CONFIG  [P1]
  society_settings                 BILLING  [P3]
  theme_settings                   bill_templates
                                     +-- bill_template_versions
  UTILITIES  [P4]                    +-- bill_template_assignments
  water_readings                   billing_runs
  electricity_readings               +-- maintenance_bills
                                           +-- bill_line_items
  ASSETS  [P4]                             +-- payments
  parking_slots
  vehicles                         OPERATIONS  [P5]
  pets                             complaints
                                     +-- complaint_comments
  COMMUNITY  [P5]                  work_schedules
  notices                            +-- work_tasks
    +-- notice_reads               visitors
  amenities                        security_incidents
    +-- amenity_bookings

  CROSS-CUTTING  [P1]
  audit_logs, notifications
```

## 2. Conventions

Same as central: UUID PKs, `TIMESTAMPTZ` UTC, native enums, `NUMERIC` money,
`created_at` / `updated_at` everywhere.

Additionally:
- Money `NUMERIC(14,2)`; utility quantities `NUMERIC(14,3)`.
- `created_by` / `updated_by` reference the tenant `users.id`.
- Deletes are hard except where financial or legal history requires otherwise
  (bills, payments, audit logs — never deleted).

## 3. Identity & access **[P1]**

### `users`

The society-local identity. Mirrors a `platform_users` row in the central DB.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | mirrored into `platform_users.tenant_user_id` |
| `firebase_uid` | TEXT NOT NULL UNIQUE | denormalised for fast principal build |
| `email` | TEXT NOT NULL | unique on `lower(email)` |
| `phone` | TEXT | `CHECK (~ '^[6-9][0-9]{9}$')` |
| `full_name` | TEXT NOT NULL | |
| `avatar_url` | TEXT | |
| `is_active` | BOOLEAN NOT NULL DEFAULT true | |
| `last_login_at` | TIMESTAMPTZ | |

```sql
CREATE UNIQUE INDEX ix_users_firebase_uid ON users (firebase_uid);
CREATE UNIQUE INDEX ix_users_email        ON users (lower(email));
CREATE INDEX        ix_users_active       ON users (is_active) WHERE is_active;
```

### `roles`, `permissions`, `role_permissions`, `user_roles`

Seeded at provisioning from `ROLE_PERMISSIONS` in `app/core/permissions.py`.

```sql
roles             (id UUID PK, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                   description TEXT, is_system BOOLEAN NOT NULL DEFAULT true)

permissions       (id UUID PK, code TEXT UNIQUE NOT NULL, resource TEXT NOT NULL,
                   action TEXT NOT NULL, description TEXT)

role_permissions  (role_id UUID FK, permission_id UUID FK,
                   PRIMARY KEY (role_id, permission_id))

user_roles        (user_id UUID FK, role_id UUID FK, assigned_by UUID FK,
                   assigned_at TIMESTAMPTZ NOT NULL,
                   PRIMARY KEY (user_id, role_id))

CREATE INDEX ix_user_roles_user ON user_roles (user_id);
```

`is_system` roles cannot be deleted or have their permission set edited through
the API — a society may add custom roles later, not weaken the built-ins.

## 4. Configuration **[P1]**

### `society_settings` — single row (`CHECK (id = 1)` singleton pattern)

| Column | Type | Notes |
|---|---|---|
| `id` | SMALLINT PK | `CHECK (id = 1)` |
| `society_name` | TEXT NOT NULL | display name inside the app |
| `registration_number` | TEXT | |
| `address_line1` / `line2` / `city` / `state` / `pincode` | TEXT | |
| `contact_email` / `contact_phone` | TEXT | |
| `timezone` | TEXT NOT NULL DEFAULT `'Asia/Kolkata'` | |
| `currency` | TEXT NOT NULL DEFAULT `'INR'` | |
| `locale` | TEXT NOT NULL DEFAULT `'en-IN'` | |
| `financial_year_start_month` | SMALLINT NOT NULL DEFAULT 4 | April — Indian FY |
| `default_billing_cycle` | `billing_frequency` NOT NULL DEFAULT `'MONTHLY'` | |
| `bill_due_days` | SMALLINT NOT NULL DEFAULT 15 | |
| `late_fee_percent` | NUMERIC(5,2) NOT NULL DEFAULT 0 | |
| `late_fee_grace_days` | SMALLINT NOT NULL DEFAULT 0 | |

### `theme_settings` — single row

| Column | Type | Notes |
|---|---|---|
| `id` | SMALLINT PK | `CHECK (id = 1)` |
| `theme_mode` | `theme_mode` NOT NULL DEFAULT `'system'` | `light`/`dark`/`system` |
| `primary_color` | TEXT NOT NULL DEFAULT `'#4F46E5'` | `CHECK (~ '^#[0-9A-Fa-f]{6}$')` |
| `secondary_color` | TEXT NOT NULL DEFAULT `'#0EA5E9'` | same check |
| `accent_color` | TEXT NOT NULL DEFAULT `'#8B5CF6'` | same check |
| `sidebar_color` | TEXT NOT NULL DEFAULT `'#101828'` | same check |
| `border_radius` | SMALLINT NOT NULL DEFAULT 14 | `CHECK (BETWEEN 0 AND 32)` |
| `logo_url` | TEXT | |
| `updated_by` | UUID FK -> users | |

The hex `CHECK` constraints matter — they are the last line of defence against a
value that would be injected into a CSS custom property.

## 5. Physical structure **[P2]**

```
buildings (id, name, code UNIQUE, description, total_floors, sort_order)
   |
blocks    (id, building_id FK, name, code, sort_order)
   |         UNIQUE (building_id, code)
floors    (id, block_id FK, number, name, sort_order)
   |         UNIQUE (block_id, number)
flats     (id, floor_id FK, building_id FK, block_id FK, ...)
```

`flats` denormalises `building_id` and `block_id` alongside `floor_id`. The
lookup "all flats in building X" is the single hottest query in billing, and
denormalising removes two joins from every billing run. Consistency is held by a
trigger that derives them from `floor_id` on insert/update, so they cannot drift.

### `flats`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `floor_id` / `block_id` / `building_id` | UUID FK NOT NULL | |
| `flat_number` | TEXT NOT NULL | "A-1203" |
| `flat_type` | TEXT | "2BHK", "3BHK" |
| `area_sqft` | NUMERIC(10,2) NOT NULL | billing input |
| `carpet_area_sqft` | NUMERIC(10,2) | |
| `occupancy_status` | `occupancy_status` NOT NULL | `OWNER_OCCUPIED`/`RENTED`/`VACANT` |
| `owner_resident_id` | UUID FK -> residents | nullable, set after residents exist |
| `base_maintenance_override` | NUMERIC(14,2) | per-flat override of the template value |
| `is_active` | BOOLEAN NOT NULL DEFAULT true | |

Flat numbers are unique **per building**, not society-wide: Tower A and Tower
B both having a flat "101" is ordinary, and forcing a prefix would make the
software argue with the signage.

```sql
CREATE UNIQUE INDEX ix_flats_number   ON flats (building_id, flat_number);
CREATE INDEX        ix_flats_building ON flats (building_id) WHERE is_active;
CREATE INDEX        ix_flats_block    ON flats (block_id)    WHERE is_active;
CREATE INDEX        ix_flats_floor    ON flats (floor_id);
```

### `residents` / `family_members`

```
residents (id, flat_id FK, user_id FK NULL, full_name, email, phone,
           resident_type ENUM(OWNER, TENANT), is_primary BOOLEAN,
           move_in_date, move_out_date, is_active)

family_members (id, resident_id FK, full_name, relationship, date_of_birth, phone)

CREATE INDEX ix_residents_flat ON residents (flat_id) WHERE is_active;
CREATE INDEX ix_residents_user ON residents (user_id) WHERE user_id IS NOT NULL;
```

`residents.user_id` is nullable: a family member or non-app-using owner exists as
a resident without a login. A `FLAT_OWNER` principal's `flat_ids` is derived
from `residents WHERE user_id = :tenant_user_id AND is_active`.

Two constraints are load-bearing rather than cosmetic:

* `ux_residents_primary` — a partial unique index giving each flat **at most
  one active primary contact**. Billing and visitor routing both assume it,
  so it is enforced by the database, not by a service convention.
* `flats.building_id` / `flats.block_id` are maintained by
  `trg_flats_derive_parents`, which derives them from `floor_id` on insert
  and update. Passing a wrong building is silently corrected rather than
  stored; moving a floor to another block re-cascades its flats.

`flats.occupancy_status` is **derived**, not free-form: adding or removing a
resident recomputes it (`VACANT` / `OWNER_OCCUPIED` / `RENTED`). A billing
formula branches on it, so a stale value would bill the wrong branch.

## 6. Billing **[P3]**

### `bill_templates`
```
(id, name, description, frequency billing_frequency, is_active,
 active_version_id UUID FK NULL, created_by, created_at, updated_at)
CREATE UNIQUE INDEX ix_tpl_name ON bill_templates (lower(name));
```

### `bill_template_versions` — append-only
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `template_id` | UUID FK NOT NULL | |
| `version_number` | INT NOT NULL | `UNIQUE (template_id, version_number)` |
| `formula` | JSONB NOT NULL | the AST |
| `line_item_spec` | JSONB NOT NULL | AST node -> presented row mapping |
| `parameters` | JSONB NOT NULL DEFAULT `'{}'` | named constants (`custom.*` fields) |
| `notes` | TEXT | changelog entry |
| `is_published` | BOOLEAN NOT NULL DEFAULT false | |
| `created_by` / `created_at` | | no `updated_at` — versions never change |

```sql
CREATE TRIGGER trg_tplver_immutable BEFORE UPDATE ON bill_template_versions
  FOR EACH ROW EXECUTE FUNCTION nf_reject_if_published();
```

### `bill_template_assignments`
```
(id, template_id FK, scope ENUM(ALL, BUILDING, BLOCK, FLAT_TYPE, FLAT),
 building_id, block_id, flat_type, flat_id, priority INT, is_active)
```
Most specific scope wins; `priority` breaks ties. Resolution is a pure function
(`resolve_template_for_flat`) with its own unit tests.

### `billing_runs`
```
(id, template_id FK, template_version_id FK, frequency, period_key TEXT,
 period_start DATE, period_end DATE, due_date DATE,
 status ENUM(PENDING, RUNNING, COMPLETED, COMPLETED_WITH_ERRORS, FAILED, PUBLISHED),
 total_flats INT, bills_generated INT, bills_failed INT,
 total_amount NUMERIC(16,2), error_summary JSONB,
 started_at, completed_at, published_at, published_by, created_by)

CREATE UNIQUE INDEX ux_run_period ON billing_runs (template_id, period_key)
    WHERE status <> 'FAILED';
```

### `maintenance_bills` — immutable once published
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `bill_number` | TEXT NOT NULL UNIQUE | `NF/2026-27/000123` |
| `billing_run_id` / `flat_id` | UUID FK NOT NULL | |
| `template_id` / `template_version_id` | UUID FK NOT NULL | **provenance** |
| `formula_snapshot` | JSONB NOT NULL | exact AST used |
| `input_snapshot` | JSONB NOT NULL | every field value read |
| `calculation_trace` | JSONB NOT NULL | powers "How was this calculated?" |
| `period_key` / `period_start` / `period_end` | | |
| `subtotal` / `penalty` / `discount` / `tax` / `total` | NUMERIC(14,2) NOT NULL | |
| `amount_paid` | NUMERIC(14,2) NOT NULL DEFAULT 0 | mutable |
| `status` | `bill_status` | `DRAFT`/`PUBLISHED`/`FAILED`/`VOID` |
| `payment_status` | `payment_status` | `UNPAID`/`PARTIAL`/`PAID`/`OVERDUE` — mutable |
| `issued_at` / `due_date` / `paid_at` | | |

```sql
CREATE UNIQUE INDEX ux_bill_flat_period ON maintenance_bills (flat_id, template_id, period_key)
    WHERE status <> 'VOID';
CREATE INDEX ix_bills_flat    ON maintenance_bills (flat_id, period_start DESC);
CREATE INDEX ix_bills_status  ON maintenance_bills (status, payment_status);
CREATE INDEX ix_bills_due     ON maintenance_bills (due_date)
    WHERE payment_status IN ('UNPAID','PARTIAL');
CREATE INDEX ix_bills_run     ON maintenance_bills (billing_run_id);

CREATE TRIGGER trg_bill_immutable BEFORE UPDATE ON maintenance_bills
  FOR EACH ROW EXECUTE FUNCTION nf_bill_guard();
```

`nf_bill_guard()` allows any change while `DRAFT`; once `PUBLISHED`, it permits
only `amount_paid`, `payment_status`, `paid_at`, `updated_at` and the
`PUBLISHED -> VOID` transition. Everything else raises.

### `bill_line_items`
```
(id, bill_id FK, sort_order INT, code TEXT, label TEXT,
 quantity NUMERIC(14,3), unit TEXT, rate NUMERIC(14,4),
 amount NUMERIC(14,2) NOT NULL, is_credit BOOLEAN NOT NULL DEFAULT false,
 meta JSONB)
CREATE INDEX ix_lineitems_bill ON bill_line_items (bill_id, sort_order);
```

### `payments`
```
(id, bill_id FK NULL, flat_id FK NOT NULL, amount NUMERIC(14,2) NOT NULL,
 method ENUM(CASH, CHEQUE, NEFT, UPI, CARD, NETBANKING, ADJUSTMENT),
 status ENUM(PENDING, SUCCESS, FAILED, REFUNDED),
 provider TEXT, provider_payment_id TEXT, provider_order_id TEXT,
 provider_payload JSONB, reference_number TEXT,
 paid_at, recorded_by FK, notes)

CREATE INDEX ix_pay_flat ON payments (flat_id, paid_at DESC);
CREATE INDEX ix_pay_bill ON payments (bill_id);
CREATE UNIQUE INDEX ux_pay_provider ON payments (provider, provider_payment_id)
    WHERE provider_payment_id IS NOT NULL;
```

That last index is the idempotency key for payment-gateway webhooks — a retried
callback cannot double-credit a flat.

## 7. Utilities **[P4]** — implemented

```
water_readings (id, flat_id FK NOT NULL, reading_date DATE NOT NULL,
                previous_reading NUMERIC(14,3), current_reading NUMERIC(14,3) NOT NULL,
                consumption NUMERIC(14,3) GENERATED ALWAYS AS
                    (current_reading - COALESCE(previous_reading,0)) STORED,
                period_key TEXT, meter_number TEXT, remarks TEXT,
                recorded_by FK -> users ON DELETE SET NULL,
                created_at, updated_at)

electricity_readings (... identical, plus amount NUMERIC(14,2) for the
                      pass-through case where the society is billed by the
                      utility and forwards the amount rather than applying
                      its own tariff)

ALTER TABLE water_readings       ADD CONSTRAINT water_flat_date       UNIQUE (flat_id, reading_date);
ALTER TABLE electricity_readings ADD CONSTRAINT electricity_flat_date UNIQUE (flat_id, reading_date);

ALTER TABLE water_readings ADD CONSTRAINT reading_non_negative CHECK (current_reading >= 0);
ALTER TABLE water_readings ADD CONSTRAINT monotonic
    CHECK (previous_reading IS NULL OR current_reading >= previous_reading);
ALTER TABLE electricity_readings ADD CONSTRAINT amount_non_negative
    CHECK (amount IS NULL OR amount >= 0);

CREATE INDEX ix_water_flat_date ON water_readings (flat_id, reading_date);
CREATE INDEX ix_water_period    ON water_readings (period_key);
CREATE INDEX ix_elec_flat_date  ON electricity_readings (flat_id, reading_date);
CREATE INDEX ix_elec_period     ON electricity_readings (period_key);
```

Three decisions are worth the space:

**`consumption` is a generated column.** Nothing in the application computes it,
so a correction applied to one of the two readings cannot leave a stale
consumption behind — and a caller that posts a `consumption` of its own is
simply ignored.

**Uniqueness is on `(flat_id, reading_date)`, not `(flat_id, period_key)`.**
The plan said period; the build says date. `period_key` is nullable, and in
PostgreSQL a nullable column in a unique constraint enforces nothing for the
rows that leave it NULL — which would have been every reading entered before
the billing period was decided. The date is always present, and "one reading
per meter per day" is the real-world rule anyway.

**Each unique constraint is named per table.** A unique constraint is backed by
an index, and index names live in the schema namespace rather than the table's,
so `water_readings` and `electricity_readings` cannot both call theirs
`flat_date`.

The monotonic `CHECK` catches a transposed meter entry at write time rather
than as a negative charge on a resident's bill. The service layer refuses the
same case earlier with a message that says what to do about a replaced meter;
the constraint is the guarantee, not the user experience.

## 8. Assets **[P4]** — implemented

```
parking_slots (id, slot_number TEXT NOT NULL, building_id FK NULL, level TEXT,
               slot_type ENUM(TWO_WHEELER, FOUR_WHEELER, VISITOR, HANDICAPPED)
                   NOT NULL DEFAULT 'FOUR_WHEELER',
               monthly_charge NUMERIC(14,2) NOT NULL DEFAULT 0,
               flat_id FK NULL ON DELETE SET NULL,   -- NULL = unallotted
               notes TEXT, is_active BOOLEAN NOT NULL DEFAULT true,
               created_at, updated_at)

vehicles (id, flat_id FK NOT NULL ON DELETE CASCADE,
          registration_number TEXT NOT NULL,
          vehicle_type ENUM(TWO_WHEELER, FOUR_WHEELER, BICYCLE, OTHER) NOT NULL,
          make, model, color, parking_slot_id FK NULL ON DELETE SET NULL,
          is_active BOOLEAN NOT NULL DEFAULT true, created_at, updated_at)

pets (id, flat_id FK NOT NULL ON DELETE CASCADE, name TEXT NOT NULL,
      pet_type ENUM(DOG, CAT, BIRD, OTHER) NOT NULL, breed,
      registration_number, vaccination_expiry DATE,
      monthly_fee NUMERIC(14,2) NOT NULL DEFAULT 0,
      is_active BOOLEAN NOT NULL DEFAULT true, created_at, updated_at)

CREATE UNIQUE INDEX ux_parking_slot_number ON parking_slots (upper(slot_number));
CREATE INDEX ix_parking_flat      ON parking_slots (flat_id) WHERE flat_id IS NOT NULL;
CREATE INDEX ix_parking_available ON parking_slots (slot_type)
    WHERE flat_id IS NULL AND is_active;

CREATE UNIQUE INDEX ux_vehicle_registration
    ON vehicles (upper(registration_number)) WHERE is_active;
CREATE INDEX ix_vehicles_flat ON vehicles (flat_id) WHERE is_active;
CREATE INDEX ix_pets_flat     ON pets (flat_id) WHERE is_active;

ALTER TABLE parking_slots ADD CONSTRAINT charge_non_negative CHECK (monthly_charge >= 0);
ALTER TABLE pets          ADD CONSTRAINT fee_non_negative    CHECK (monthly_fee >= 0);
```

The registration index is unique on `upper(...)` and **partial on `is_active`**:
a plate must resolve to exactly one flat for the gate to be useful, but a
vehicle that has left the society is deactivated rather than deleted — a gate
log referencing it must still resolve to the flat it belonged to at the time —
and its registration becomes available to whoever buys the car.

`monthly_charge` and `monthly_fee` live here rather than on each bill because
the billing engine reads them through the `parking_charge_total` and
`pet_fee_total` fields. Entering them per bill would make the two disagree.

## 9. Operations **[P5]** — implemented

```
complaints          (id, ticket_number UNIQUE NOT NULL DEFAULT <see below>,
                     flat_id FK NULL, raised_by FK NULL, raised_by_name,
                     title, description,
                     category ENUM(PLUMBING, ELECTRICAL, LIFT, HOUSEKEEPING,
                                   SECURITY, PARKING, NOISE, WATER_SUPPLY,
                                   COMMON_AREA, BILLING, OTHER),
                     priority ENUM(LOW, MEDIUM, HIGH, URGENT),
                     status ENUM(OPEN, ACKNOWLEDGED, IN_PROGRESS, RESOLVED,
                                 CLOSED, REJECTED, REOPENED),
                     location, assigned_to FK NULL, assigned_department ENUM NULL,
                     due_by, acknowledged_at, resolved_at, closed_at,
                     resolution_notes, reopen_count SMALLINT, rating, rating_comment)

complaint_comments  (id, complaint_id FK, author_id FK NULL, author_name, body,
                     is_internal BOOLEAN, is_system BOOLEAN)

work_schedules      (id, department ENUM(MAINTENANCE, HOUSEKEEPING), title,
                     description, area, building_id FK NULL,
                     recurrence ENUM(DAILY, WEEKLY, FORTNIGHTLY, MONTHLY,
                                     QUARTERLY, HALF_YEARLY, YEARLY),
                     priority, assigned_to FK NULL, estimated_cost, vendor_name,
                     vendor_phone, starts_on, next_due_on, ends_on,
                     lead_days SMALLINT, is_active)

work_tasks          (id, department ENUM, schedule_id FK NULL, complaint_id FK NULL,
                     title, description, area, building_id FK NULL,
                     status ENUM(PENDING, IN_PROGRESS, COMPLETED, VERIFIED,
                                 CANCELLED, SKIPPED),
                     priority, assigned_to FK NULL, due_on DATE,
                     started_at, completed_at, completed_by FK NULL,
                     verified_at, verified_by FK NULL,
                     completion_notes, actual_cost, vendor_name)

visitors            (id, pass_code, flat_id FK, visitor_name, visitor_phone,
                     visitor_type ENUM(GUEST, DELIVERY, CAB, SERVICE,
                                       DOMESTIC_HELP, VENDOR, OTHER),
                     company, purpose, accompanying_count, vehicle_number,
                     status ENUM(EXPECTED, AWAITING_APPROVAL, APPROVED, DENIED,
                                 CHECKED_IN, CHECKED_OUT, EXPIRED),
                     expected_from, expected_to, approved_by FK NULL, approved_at,
                     denial_reason, checked_in_at, checked_in_by FK NULL,
                     checked_out_at, checked_out_by FK NULL, notes)

security_incidents  (id, title, description,
                     severity ENUM(INFO, MINOR, MAJOR, CRITICAL),
                     status ENUM(REPORTED, INVESTIGATING, RESOLVED, CLOSED),
                     location, building_id FK NULL, flat_id FK NULL,
                     occurred_at NOT NULL, reported_by FK NULL, reported_by_name,
                     action_taken, resolved_at, police_reference, people_involved)
```

**Maintenance and housekeeping are one pair of tables, not two.** They have
identical workflows and separate permissions, so `department` tells them apart.
Two sets would have drifted apart by the third bug fix; a repository scoped to
one department at construction is what keeps a housekeeping supervisor from
being one missing `WHERE` away from the lift service contract.

**A schedule is not a task.** `work_schedules` is the intention ("the lift is
serviced monthly"); `work_tasks` is what happened on a given date. The scheduler
creates the second from the first, which is why a skipped month is *visible*
rather than silently absent.

### The ticket number is the database's

```sql
CREATE SEQUENCE complaint_ticket_seq START 1;

ALTER TABLE complaints ALTER COLUMN ticket_number SET DEFAULT
  'CMP-' || to_char(now() AT TIME ZONE 'Asia/Kolkata', 'YYYY') || '-' ||
  lpad(nextval('complaint_ticket_seq')::text, 5, '0');
```

`CMP-2026-00042`. Two residents pressing Submit in the same millisecond cannot
be handed the same number, and no service holds a lock to avoid it. The year is
computed in IST so the ticket matches the day the resident remembers raising it
rather than the server's UTC date.

### Constraints that carry the workflow

| Invariant | Enforced by |
|---|---|
| A resolution cannot predate its complaint | `CHECK (resolved_at IS NULL OR resolved_at >= created_at)` |
| A rating is 1–5 | `CHECK (rating BETWEEN 1 AND 5)` |
| A task cannot be verified without being completed | `CHECK (verified_at IS NULL OR completed_at IS NOT NULL)` |
| One task per schedule per due date | `ux_work_tasks_occurrence` — unique, partial on `schedule_id IS NOT NULL` |
| A visitor cannot check out without checking in | `CHECK (checked_out_at IS NULL OR checked_in_at IS NOT NULL)` |
| …and cannot leave before arriving | `CHECK (checked_out_at IS NULL OR checked_out_at >= checked_in_at)` |
| A pass code identifies one *live* pass | `ux_visitors_pass_code` — unique, partial on the four live statuses |

The occurrence index is what makes task generation idempotent: the nightly sweep
can be restarted halfway through and re-running it creates nothing.

The pass-code index is partial on purpose. Once a visit is over the code is free
again, which keeps codes to six characters — short enough to read out over a
phone to a guard at a gate.

```sql
CREATE INDEX ix_complaints_status     ON complaints (status, created_at);
CREATE INDEX ix_complaints_flat       ON complaints (flat_id) WHERE flat_id IS NOT NULL;
CREATE INDEX ix_complaints_open_due   ON complaints (due_by)
    WHERE status IN ('OPEN','ACKNOWLEDGED','IN_PROGRESS','REOPENED');
CREATE INDEX ix_work_schedules_due    ON work_schedules (next_due_on) WHERE is_active;
CREATE INDEX ix_work_tasks_open       ON work_tasks (due_on)
    WHERE status IN ('PENDING','IN_PROGRESS');
CREATE INDEX ix_visitors_on_premises  ON visitors (checked_in_at) WHERE status = 'CHECKED_IN';
CREATE INDEX ix_incidents_open        ON security_incidents (severity)
    WHERE status IN ('REPORTED','INVESTIGATING');
```

`next_due_on` is *stored* rather than computed on read. The scheduler asks "what
is due today" across every society every morning, and a stored date turns that
into an index scan instead of a recurrence calculation per row.

## 10. Community **[P5]** — implemented

```
notices           (id, title, body,
                   category ENUM(GENERAL, URGENT, MAINTENANCE, EVENT, MEETING,
                                 BILLING, SECURITY),
                   priority ENUM, audience ENUM(ALL, BUILDING, BLOCK, OWNERS,
                                                TENANTS, STAFF),
                   building_id FK NULL, block_id FK NULL,
                   is_pinned, is_published, publish_at, expires_at,
                   attachments JSONB, author_id FK NULL, author_name)

notice_reads      (id, notice_id FK, user_id FK, read_at,
                   UNIQUE (notice_id, user_id))

amenities         (id, name, description, location, building_id FK NULL, capacity,
                   opens_at TIME, closes_at TIME, slot_minutes SMALLINT,
                   booking_charge NUMERIC(14,2), max_advance_days,
                   max_slots_per_booking, max_active_per_flat,
                   requires_approval, rules, is_active)

amenity_bookings  (id, amenity_id FK, flat_id FK, booked_by FK NULL,
                   booked_by_name, booking_date DATE, starts_at, ends_at,
                   slots SMALLINT, guests SMALLINT, purpose,
                   status ENUM(PENDING, CONFIRMED, CANCELLED, REJECTED,
                               COMPLETED, NO_SHOW),
                   charge NUMERIC(14,2), approved_by FK NULL, approved_at,
                   cancelled_at, cancellation_reason)
```

### A slot cannot be double-booked

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- UUID equality inside a GiST index

ALTER TABLE amenity_bookings ADD CONSTRAINT no_overlapping_bookings
  EXCLUDE USING gist (
    amenity_id WITH =,
    tstzrange(starts_at, ends_at, '[)') WITH &&
  ) WHERE (status IN ('PENDING', 'CONFIRMED'));
```

Thirty people trying to book the party lawn at 9 a.m. on a Sunday is not a rare
case in a 300-flat society, and an application-level "check availability, then
insert" loses that race every time. The service checks the *rules* — advance
limit, slots per booking, quota per flat, slot alignment — so a resident gets a
sentence they can act on; the *race* is left entirely to this constraint, and
the loser gets a 409.

The `WHERE` clause is the half that is easy to forget: without it a cancelled
booking keeps holding the clubhouse forever.

The insert runs inside a **SAVEPOINT**. The constraint firing is the expected
outcome of a race, not a failure of the request, and rolling the whole
transaction back would take the audit entry with it and leave the session
unusable for the error response.

`notice_reads` is keyed on `(notice_id, user_id)` and written with
`ON CONFLICT DO NOTHING`, so a double-tap on a slow connection cannot inflate
the read count a committee uses to decide whether anyone saw the AGM notice.

`amenity_bookings.charge` is snapshotted at booking time — the same rule the
billing engine applies to a published bill. A rate rise next month must not
change what a resident already agreed to pay.

```sql
CREATE INDEX ix_notices_published  ON notices (publish_at) WHERE is_published;
CREATE INDEX ix_notices_pinned     ON notices (is_pinned, publish_at) WHERE is_published;
CREATE UNIQUE INDEX ux_amenities_name ON amenities (lower(name));
CREATE INDEX ix_bookings_amenity_date ON amenity_bookings (amenity_id, booking_date);
CREATE INDEX ix_bookings_upcoming     ON amenity_bookings (starts_at)
    WHERE status IN ('PENDING', 'CONFIRMED');
```

## 11. Cross-cutting **[P1]**

```
audit_logs    (id BIGSERIAL PK, request_id, action, actor_id FK NULL, actor_email,
               target_type, target_id, changes JSONB, ip_address INET,
               user_agent, status, created_at)

notifications (id, user_id FK, channel ENUM(IN_APP, EMAIL, PUSH, SMS, WHATSAPP),
               category, title, body, link, payload JSONB,
               is_read BOOLEAN NOT NULL DEFAULT false, read_at, sent_at, created_at)

CREATE INDEX ix_audit_created ON audit_logs (created_at DESC);
CREATE INDEX ix_audit_actor   ON audit_logs (actor_id, created_at DESC);
CREATE INDEX ix_notif_unread  ON notifications (user_id, created_at DESC) WHERE NOT is_read;
```

## 12. Indexing philosophy

Indexes exist for queries that actually run. Every index above traces to a
specific screen or job:

| Index | Serves |
|---|---|
| `ix_users_firebase_uid` | principal resolution, every request |
| `ix_flats_building` | billing run flat resolution |
| `ix_bills_flat` | resident bill history |
| `ix_bills_due` | overdue sweep, dunning |
| `ix_water_flat_date` | resident consumption chart |
| `ix_visitors_on_premises` | the guard's board: who is inside right now |
| `ix_work_tasks_open` | a worker's list, and the overdue count |
| `ix_complaints_open_due` | the overdue banner on the operations dashboard |
| `ix_notif_unread` | notification bell badge |

Partial indexes (`WHERE is_active`, `WHERE NOT is_read`) are used deliberately —
they stay small and the planner picks them for exactly the query shape the UI
issues.

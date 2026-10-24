# RBAC — Roles, Permissions, Matrix

## 1. Principles

1. **Permissions are the currency, not roles.** Code asks
   `require_permission(Permission.BILLING_PUBLISH)`, never
   `if user.role == "SOCIETY_ADMIN"`.
2. **Permissions are a closed enum**, defined once in
   `app/core/permissions.py`. A typo is an `AttributeError` at import, not a
   silent authorization hole.
3. **Roles are data.** `roles`, `permissions` and `role_permissions` are seeded
   into each tenant database at provisioning, so a society can later be granted
   a custom role without a deploy.
4. **Ownership scoping is separate from permission.** `BILL_READ` says you may
   read bills; `Principal.owns_flat()` decides *which*. A Flat Owner and a
   Society Admin share `BILL_READ` but the service applies an owner filter when
   the principal lacks `BILL_READ_ALL`.
5. **Deny by default.** No permission, no access. There is no implicit grant and
   no wildcard except `SUPER_ADMIN`, which is checked explicitly and never
   receives a tenant session.

## 2. Roles

| Role | Scope | Purpose |
|---|---|---|
| `SUPER_ADMIN` | Platform (central DB) | Operates NestFlow itself: creates societies, manages plans and subscriptions, locks/unlocks. Has **no** tenant data access. |
| `SOCIETY_ADMIN` | One society | Full authority inside their society. |
| `FLAT_OWNER` | Own flat(s) | Resident. Reads own bills/utilities, manages own vehicles/pets/visitors, raises complaints. |
| `MAINTENANCE_ADMIN` | One society | Manages maintenance staff, tasks, assignments; triages complaints. |
| `MAINTENANCE` | Own tasks | Field worker. Sees and progresses assigned tasks only. |
| `HOUSEKEEPER_ADMIN` | One society | Manages housekeeping staff, schedules, attendance. |
| `HOUSEKEEPER` | Own tasks | Sees and progresses own tasks only. |
| `SECURITY_ADMIN` | One society | Manages guards, shifts, incidents; full visitor log. |
| `SECURITY` | Gate | Logs visitor/delivery/vehicle entry, requests resident approval. |

A tenant user may hold more than one role; the effective permission set is the
union.

## 3. Permission catalogue

Format: `<resource>.<action>`.

### Platform (central DB, SUPER_ADMIN only)

```
platform.society.read          platform.subscription.read
platform.society.create        platform.subscription.assign
platform.society.update        platform.subscription.extend
platform.society.lock          platform.subscription.suspend
platform.society.unlock        platform.plan.read
platform.society.archive       platform.plan.create
platform.user.read             platform.plan.update
platform.user.create           platform.audit.read
platform.user.update
platform.user.disable
```

### Society

```
society.read              society.update            society.settings.manage
theme.read                theme.update
```

### Structure & people

```
building.read   building.manage        flat.read     flat.manage
block.read      block.manage           resident.read resident.manage
floor.read      floor.manage           user.read     user.create
                                       user.update   user.delete
                                       role.assign
```

### Billing

```
billing.read              read own bills (scoped by flat ownership)
billing.read_all          read every flat's bills
billing.create            trigger a billing run
billing.update            edit a DRAFT bill
billing.publish           publish a run (irreversible)
billing.manage_template   create/edit templates and versions
```

### Utilities & assets

```
water.read        water.manage          parking.read    parking.manage
electricity.read  electricity.manage    vehicle.read    vehicle.manage
                                        pet.read        pet.manage
```

`*.read` is own-scoped for residents. `*.manage` implies society-wide read —
**but only when the holder's own `*.manage` is itself society-wide**. See
section 6.

### Operations

```
complaint.read      complaint.create    complaint.manage
maintenance.read    maintenance.manage  maintenance.task.progress
housekeeping.read   housekeeping.manage housekeeping.task.progress
security.read       security.manage
visitor.create      visitor.read        visitor.approve
notice.read         notice.manage
amenity.read        amenity.book        amenity.manage
```

### Money & comms

```
payment.read    payment.record    payment.refund
notification.read    notification.send
report.read
audit.read
```

## 4. Role → permission matrix

Legend: **●** granted · **◐** granted but scoped to own records · ·  not granted

| Permission | SUPER<br>ADMIN | SOCIETY<br>ADMIN | FLAT<br>OWNER | MAINT<br>ADMIN | MAINT | HK<br>ADMIN | HK | SEC<br>ADMIN | SEC |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| `platform.*` | ● | · | · | · | · | · | · | · | · |
| `society.read` | · | ● | ● | ● | ● | ● | ● | ● | ● |
| `society.update` | · | ● | · | · | · | · | · | · | · |
| `society.settings.manage` | · | ● | · | · | · | · | · | · | · |
| `theme.read` | · | ● | ● | ● | ● | ● | ● | ● | ● |
| `theme.update` | · | ● | · | · | · | · | · | · | · |
| `building.read` `block.read` `floor.read` | · | ● | · | ● | · | ● | · | ● | · |
| `building.manage` `block.manage` `floor.manage` | · | ● | · | · | · | · | · | · | · |
| `flat.read` | · | ● | ◐ | ● | · | ● | · | ● | ● |
| `flat.manage` | · | ● | · | · | · | · | · | · | · |
| `resident.read` | · | ● | ◐ | · | · | · | · | ● | ● |
| `resident.manage` | · | ● | · | · | · | · | · | · | · |
| `user.read` | · | ● | · | ● | · | ● | · | ● | · |
| `user.create` `user.update` `user.delete` `role.assign` | · | ● | · | · | · | · | · | · | · |
| `billing.read` | · | ● | ◐ | · | · | · | · | · | · |
| `billing.read_all` | · | ● | · | · | · | · | · | · | · |
| `billing.create` `billing.update` | · | ● | · | · | · | · | · | · | · |
| `billing.publish` | · | ● | · | · | · | · | · | · | · |
| `billing.manage_template` | · | ● | · | · | · | · | · | · | · |
| `water.read` `electricity.read` | · | ● | ◐ | · | · | · | · | · | · |
| `water.manage` `electricity.manage` | · | ● | · | ● | · | · | · | · | · |
| `parking.read` | · | ● | ◐ | · | · | · | · | ● | ● |
| `parking.manage` | · | ● | · | · | · | · | · | · | · |
| `vehicle.read` | · | ● | ◐ | · | · | · | · | ● | ● |
| `vehicle.manage` | · | ● | ◐ | · | · | · | · | · | · |
| `pet.read` | · | ● | ◐ | · | · | · | · | · | · |
| `pet.manage` | · | ● | ◐ | · | · | · | · | · | · |
| `complaint.create` | · | ● | ● | ● | · | ● | · | ● | · |
| `complaint.read` | · | ● | ◐ | ● | ◐ | ● | ◐ | ● | · |
| `complaint.manage` | · | ● | · | ● | · | ● | · | · | · |
| `maintenance.read` | · | ● | · | ● | ◐ | · | · | · | · |
| `maintenance.manage` | · | ● | · | ● | · | · | · | · | · |
| `maintenance.task.progress` | · | · | · | ● | ◐ | · | · | · | · |
| `housekeeping.read` | · | ● | · | · | · | ● | ◐ | · | · |
| `housekeeping.manage` | · | ● | · | · | · | ● | · | · | · |
| `housekeeping.task.progress` | · | · | · | · | · | ● | ◐ | · | · |
| `security.read` | · | ● | · | · | · | · | · | ● | ◐ |
| `security.manage` | · | ● | · | · | · | · | · | ● | · |
| `visitor.create` | · | ● | ● | · | · | · | · | ● | ● |
| `visitor.read` | · | ● | ◐ | · | · | · | · | ● | ● |
| `visitor.approve` | · | · | ◐ | · | · | · | · | ● | · |
| `notice.read` | · | ● | ● | ● | ● | ● | ● | ● | ● |
| `notice.manage` | · | ● | · | · | · | · | · | · | · |
| `amenity.read` | · | ● | ● | · | · | · | · | · | · |
| `amenity.book` | · | ● | ◐ | · | · | · | · | · | · |
| `amenity.manage` | · | ● | · | · | · | · | · | · | · |
| `payment.read` | · | ● | ◐ | · | · | · | · | · | · |
| `payment.record` | · | ● | ◐ | · | · | · | · | · | · |
| `payment.refund` | · | ● | · | · | · | · | · | · | · |
| `notification.read` | · | ● | ● | ● | ● | ● | ● | ● | ● |
| `notification.send` | · | ● | · | ● | · | ● | · | ● | · |
| `report.read` | · | ● | · | ● | · | ● | · | ● | · |
| `audit.read` | · | ● | · | · | · | · | · | · | · |

### Notes on the scoped (◐) cells

- **FLAT_OWNER** everywhere means "rows whose `flat_id` is in
  `Principal.flat_ids`". Enforced in the service layer, not the router.
- **A resident holds no `building.read` / `block.read` / `floor.read`.** Those
  exist to serve the Structure management screen, and a flat already carries
  its building, block and floor names denormalised — so a resident sees where
  they live without being able to enumerate the whole estate.
- **`visitor.approve` for FLAT_OWNER** means approving visitors requesting
  entry *to their own flat*. `SECURITY_ADMIN` may override.
- **MAINTENANCE / HOUSEKEEPER** means "tasks where `assigned_to = tenant_user_id`".
- **`*.task.progress` is deliberately absent from SOCIETY_ADMIN.** A Society
  Admin oversees the work but does not personally mark a worker's task done —
  that grant belongs to the worker roles, so "who completed it" stays honest.
  The `POST /{dept}/tasks/{id}/progress` route therefore accepts *either*
  `*.task.progress` **or** `*.manage`, and separates the moves inside: a worker
  can start and complete a task, while `VERIFIED` and `CANCELLED` need
  `*.manage`. That split is what makes "done" and "checked" different facts.
- **`report.read` and `billing.read_all` are the only ways into `/reports`.**
  Every report aggregates across the whole society, so an owner-scoped
  permission must never open that door — an assertion at import refuses to
  start the process if a report is ever registered against one. A `SECURITY_ADMIN`
  holding `report.read` sees the gate-traffic report and not the defaulter
  list, and the one they cannot run returns **404**, not 403.
- **`vehicle.manage` / `pet.manage` for FLAT_OWNER** covers their own flat's
  vehicles and pets only; assigning a *parking slot* remains `parking.manage`
  (admin), because slots are a shared society resource. This is exactly the
  case section 6 exists to get right: a resident holds `vehicle.manage` and
  must still not be able to read the society's whole vehicle register.
- **SECURITY** sees the visitor log for the current shift plus flats/residents
  needed to route a visitor — never bills, utilities or payments.

## 5. Implementation

```python
# app/core/permissions.py
class Permission(StrEnum):
    SOCIETY_READ = "society.read"
    BILLING_PUBLISH = "billing.publish"
    ...

class Role(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ...

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = { ... }
```

`ROLE_PERMISSIONS` is the seed source of truth. Provisioning writes it into the
tenant `roles` / `permissions` / `role_permissions` tables; runtime reads the
*tables*, so a per-society customisation is possible later without changing the
default.

A drift test (`test_rbac.py::test_seeded_matrix_matches_code`) asserts the
seeded tables equal `ROLE_PERMISSIONS` for a freshly provisioned society, so the
matrix in this document and the database cannot silently diverge.

## 6. Owner scoping and broadening

Two structures decide how far a permission reaches:

- `OWNER_SCOPED_PERMISSIONS` — permissions whose reach is narrowed to the
  principal's own flats.
- `BROADENING_PERMISSIONS` — a map from each of those to the permissions that
  lift the narrowing.

Services never ask "is this a FLAT_OWNER?". They ask
`principal.is_scoped_to_own(permission)`, so a principal who holds a genuinely
society-wide permission is correctly not narrowed, and a role added later gets
the right answer without any service being touched.

**Broadening is transitive, and that is not a detail.** A broadener only lifts
the scope if the principal's hold of *it* is itself society-wide:

```python
def is_owner_scoped(permission, held, _seen=frozenset()):
    if permission not in OWNER_SCOPED_PERMISSIONS:
        return False
    if permission in _seen:
        return True          # a cycle; staying scoped is the safe answer
    seen = _seen | {permission}
    for broadener in BROADENING_PERMISSIONS.get(permission, frozenset()):
        if broadener in held and not is_owner_scoped(broadener, held, seen):
            return False
    return True
```

A membership check alone — `BROADENING_PERMISSIONS[p] & held` — leaks the
society. `vehicle.manage` broadens `vehicle.read`, and a FLAT_OWNER holds
`vehicle.manage` so they can register their own car. Under a membership check
that resident could enumerate every vehicle in the society and the flat each
plate belongs to. Their `vehicle.manage` is only society-wide if they also hold
`parking.manage`, which a resident does not — and the recursion is what asks
that question. The same applies to `pet.manage` broadening `pet.read`, whose
escape hatch is `resident.manage`.

`security.read` broadens `flat.read`, `vehicle.read`, `parking.read` and
`visitor.read`. It is not itself owner-scoped and a guard holds no flats of
their own, so the recursion terminates there and a guard sees what a gate needs.

Regression:
`test_utilities.py::test_a_residents_manage_permission_does_not_widen_their_reads`.

## 7. Out-of-scope records return 404, not 403

A scoped principal asking for a record outside their scope gets
`NotFoundError`, not `ResourceForbiddenError`. A 403 confirms the record
exists, which is enough to enumerate a society's flats, bills or meters one id
at a time. The permission guard still returns 403 for a permission the
principal simply does not hold — that reveals nothing about data.

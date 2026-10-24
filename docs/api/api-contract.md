# API Contract

Base path: **`/api/v1`** · OpenAPI: `/api/v1/openapi.json` · Docs: `/docs`

The generated OpenAPI document is the formal contract. This file explains the
conventions that document assumes.

## 1. Envelope

Every response — success or failure — is wrapped.

**Success**
```json
{ "success": true, "data": { }, "message": "" }
```

**Paginated** (`data` is a page object)
```json
{
  "success": true,
  "data": {
    "items": [],
    "page": 1,
    "limit": 25,
    "total": 348,
    "pages": 14,
    "has_next": true,
    "has_prev": false
  },
  "message": ""
}
```

**Error**
```json
{
  "success": false,
  "code": "SUBSCRIPTION_EXPIRED",
  "message": "Your society subscription has ended. Please contact your society administrator.",
  "details": null,
  "request_id": "01JD8Z2K9Q3M7X"
}
```

`code` is a stable machine identifier the client switches on. `message` is
user-presentable English. `details` carries field errors for validation
failures. `request_id` appears on every response (also as the `X-Request-Id`
header) and is the correlation key into the structured logs.

Validation failure `details`:
```json
{
  "code": "VALIDATION_ERROR",
  "details": { "fields": [
      { "field": "contact_phone", "message": "Not a valid Indian mobile number" }
  ]}
}
```

FastAPI's default `{"detail": ...}` shape is overridden by exception handlers on
`RequestValidationError`, `HTTPException` and `NestFlowError` so no endpoint can
leak the unwrapped form.

## 2. Error codes

### Authentication — 401
| Code | Meaning |
|---|---|
| `UNAUTHENTICATED` | No / malformed `Authorization` header |
| `TOKEN_INVALID` | Signature, issuer or audience rejected |
| `TOKEN_EXPIRED` | ID token past `exp` |
| `TOKEN_REVOKED` | Session revoked in Firebase |
| `USER_NOT_REGISTERED` | Valid Firebase identity, no NestFlow account |

### Authorization — 403
| Code | Meaning |
|---|---|
| `PERMISSION_DENIED` | Principal lacks the required permission |
| `USER_DISABLED` | Account deactivated |
| `SOCIETY_LOCKED` | Society locked by the platform |
| `SOCIETY_SUSPENDED` | Society suspended |
| `SOCIETY_ARCHIVED` | Society archived |
| `SOCIETY_PROVISIONING` | Tenant DB not ready yet |
| `RESOURCE_FORBIDDEN` | Permission held, but not for *this* record (ownership scope) |

### Entitlement — 402
| Code | Meaning |
|---|---|
| `SUBSCRIPTION_EXPIRED` | Current subscription past `end_date` |
| `SUBSCRIPTION_SUSPENDED` | Suspended by the platform |
| `SUBSCRIPTION_MISSING` | No current subscription |
| `PLAN_LIMIT_EXCEEDED` | `max_flats` / `max_users` reached |

402 rather than 403 is intentional: the client renders a billing wall, not an
access-denied page.

### Resource / request
| Code | HTTP | |
|---|---|---|
| `NOT_FOUND` | 404 | |
| `ALREADY_EXISTS` | 409 | |
| `CONFLICT` | 409 | Concurrent modification / illegal state transition |
| `VALIDATION_ERROR` | 422 | |
| `RATE_LIMITED` | 429 | `Retry-After` header set |

### Domain
| Code | HTTP | |
|---|---|---|
| `INVALID_FORMULA` | 422 | `details.errors[]` from the validator |
| `DIVISION_BY_ZERO` | 422 | |
| `BILL_IMMUTABLE` | 409 | Attempt to modify a published bill |
| `BILLING_RUN_IN_PROGRESS` | 409 | |
| `DUPLICATE_BILLING_PERIOD` | 409 | |
| `TEMPLATE_VERSION_PUBLISHED` | 409 | Attempt to edit a published version |
| `PROVISIONING_FAILED` | 500 | `details.step` names the failing stage |

### Server — 5xx
`INTERNAL_ERROR` (500), `DATABASE_UNAVAILABLE` (503), `TENANT_DB_UNAVAILABLE` (503).
Stack traces are never returned; the `request_id` is how support correlates.

## 3. Conventions

**Pagination** — `?page=1&limit=25`. `limit` max 100, default 25.
**Sorting** — `?sort=created_at&order=desc`. Sortable fields are enumerated per
endpoint; an unknown field is a 422, not a silent ignore (that would otherwise
be an injection surface).
**Search** — `?q=` free text over endpoint-defined columns.
**Filtering** — explicit named params (`?status=UNPAID&building_id=...`), never a
generic query-object.
**Dates** — ISO-8601 with offset, UTC on the wire. The client renders in
`Asia/Kolkata`.
**Money** — JSON *string* decimals (`"12950.00"`), never floats. Losing paise to
IEEE-754 in a billing product is not acceptable.
**Idempotency** — mutating platform operations accept `Idempotency-Key`.

**No `society_id` appears in any request** — path, query, body or header. It is
resolved server-side. See [tenant-isolation.md](../architecture/tenant-isolation.md).

## 4. Endpoint map

**Legend** — P1 = built in Phase 1.

### `/auth` **[P1]**
| Method | Path | Permission | |
|---|---|---|---|
| GET | `/auth/me` | authenticated | Principal + society + theme + nav. One call bootstraps the app. |
| POST | `/auth/session` | authenticated | Records login, updates `last_login_at`, audits. |
| GET | `/auth/permissions` | authenticated | Effective permission list. |

### `/platform` — SUPER_ADMIN only, central DB **[P1]**
| Method | Path | Permission |
|---|---|---|
| GET | `/platform/dashboard` | `platform.society.read` |
| GET | `/platform/societies` | `platform.society.read` |
| POST | `/platform/societies` | `platform.society.create` — triggers provisioning |
| GET | `/platform/societies/{id}` | `platform.society.read` |
| PATCH | `/platform/societies/{id}` | `platform.society.update` |
| POST | `/platform/societies/{id}/lock` | `platform.society.lock` |
| POST | `/platform/societies/{id}/unlock` | `platform.society.unlock` |
| POST | `/platform/societies/{id}/archive` | `platform.society.archive` |
| POST | `/platform/societies/{id}/retry-provisioning` | `platform.society.create` |
| GET/POST | `/platform/societies/{id}/admins` | `platform.user.read` / `.create` |
| GET/POST/PATCH | `/platform/plans` | `platform.plan.*` |
| GET/POST | `/platform/subscriptions` | `platform.subscription.*` |
| POST | `/platform/subscriptions/{id}/extend` | `platform.subscription.extend` |
| POST | `/platform/subscriptions/{id}/suspend` | `platform.subscription.suspend` |
| GET | `/platform/users` | `platform.user.read` |
| GET | `/platform/audit-logs` | `platform.audit.read` |

Note `POST /platform/societies` is the **only** endpoint that takes a society
identity as input — because it is creating one.

### `/society` **[P1]**
| Method | Path | Permission |
|---|---|---|
| GET | `/society` | `society.read` |
| PATCH | `/society` | `society.update` |
| GET | `/society/settings` | `society.read` |
| PUT | `/society/settings` | `society.settings.manage` |
| GET | `/society/dashboard` | `society.read` |

### `/theme` **[P1]**
| GET | `/theme` | `theme.read` |
| PUT | `/theme` | `theme.update` |
| POST | `/theme/reset` | `theme.update` |
| POST | `/theme/logo` | `theme.update` (multipart) |

### `/users` **[P1]**
| GET | `/users` | `user.read` |
| POST | `/users` | `user.create` |
| GET/PATCH/DELETE | `/users/{id}` | `user.read` / `.update` / `.delete` |
| PUT | `/users/{id}/roles` | `role.assign` |

### `/buildings` `/blocks` `/floors` `/flats` `/residents` **[P2]**

| Method | Path | Permission |
|---|---|---|
| GET | `/structure/summary` | `building.read` |
| GET | `/structure/tree` | `building.read` |
| GET/POST | `/buildings` | `building.read` / `.manage` |
| GET/PATCH/DELETE | `/buildings/{id}` | `building.read` / `.manage` |
| GET/POST | `/blocks` | `block.read` / `.manage` |
| GET/PATCH/DELETE | `/blocks/{id}` | `block.read` / `.manage` |
| GET/POST | `/floors` | `floor.read` / `.manage` |
| POST | `/floors/range` | `floor.manage` — creates a contiguous run |
| GET/PATCH/DELETE | `/floors/{id}` | `floor.read` / `.manage` |
| GET | `/flats` | `flat.read` — **owner-scoped** |
| POST | `/flats` | `flat.manage` |
| POST | `/flats/bulk` | `flat.manage` — generate from a numbering pattern; `dry_run` previews |
| GET/PATCH/DELETE | `/flats/{id}` | `flat.read` / `.manage` |
| GET | `/residents` | `resident.read` — **owner-scoped** |
| POST | `/residents` | `resident.manage` |
| GET/PATCH/DELETE | `/residents/{id}` | `resident.read` / `.manage` |
| GET | `/residents/{id}/family` | `resident.read` |
| POST/PATCH/DELETE | `/family-members` | `resident.manage` |

**Owner scoping.** A principal whose `flat.read` is owner-scoped (a resident)
sees only rows for flats in `Principal.flat_ids`. A record outside that scope
returns **404, not 403** — a scoped principal must not be able to confirm that a
neighbour's flat exists. The narrowing happens in the service layer, and no
filter or query parameter can widen it.

### Phase 3 and 4 — billing, utilities, assets
```
/bill-templates  /bill-templates/{id}/versions        [P3]  billing.manage_template
/bill-templates/validate-formula                      [P3]  billing.manage_template
/bill-templates/{id}/preview                          [P3]  billing.manage_template
/billing/runs  /billing/runs/{id}/publish             [P3]  billing.create / .publish
/billing/bills /billing/bills/{id}                    [P3]  billing.read
/billing/bills/{id}/calculation                       [P3]  billing.read
/payments                                             [P3]  payment.read / .record
/water/readings  /electricity/readings                [P4]  *.read / *.manage
/water/readings/bulk  /electricity/readings/bulk      [P4]  *.manage
/water/pending  /electricity/pending                  [P4]  *.manage
/water/trend/{flat_id}  /electricity/trend/{flat_id}  [P4]  *.read   (owner-scoped)
/water/society-trend  /electricity/society-trend      [P4]  *.manage
/parking/slots  /parking/slots/{id}                   [P4]  parking.read / .manage
/parking/slots/{id}/allotment  /parking/summary       [P4]  parking.manage
/vehicles  /vehicles/{id}                             [P4]  vehicle.read / .manage
/pets  /pets/{id}                                     [P4]  pet.read / .manage
/dashboard/resident                                   [P4]  billing.read  (own flats)
/dashboard/utilities                                  [P4]  water.manage
```

### `/complaints` **[P5]**

| Method | Path | Permission |
|---|---|---|
| GET | `/complaints` | `complaint.read` — **owner-scoped** |
| GET | `/complaints/summary` | `complaint.manage` |
| GET | `/complaints/{id}` | `complaint.read` — with timeline and `allowed_transitions` |
| POST | `/complaints` | `complaint.create` |
| PATCH | `/complaints/{id}` | `complaint.read` (own ticket) or `complaint.manage` |
| POST | `/complaints/{id}/assignment` | `complaint.manage` |
| POST | `/complaints/{id}/transition` | `complaint.read` — the move is checked against the workflow |
| POST | `/complaints/{id}/rating` | `complaint.read` — the raiser only, once resolved |
| POST | `/complaints/{id}/comments` | `complaint.read` — `is_internal` needs `complaint.manage` |

**Status is never a writable field.** A ticket moves through
`POST /{id}/transition`, because each move has side effects — a timestamp, a
timeline entry, a notification — that a `PATCH {"status": …}` would skip.
Illegal moves return **409** with a message naming the moves that *are* legal.

`allowed_transitions` on the detail response is computed from the same table
the API enforces, so a client renders its buttons from the server's rules and
cannot offer one that would be refused.

**Owner scoping is not a plain `flat_id` filter.** A complaint with no flat is a
common-area problem and is visible to everyone; a neighbour's flat-scoped ticket
returns **404**.

### `/maintenance` `/housekeeping` **[P5]**

Identical shapes under two prefixes, generated from one route factory. Replace
`{dept}` with `maintenance` or `housekeeping`, and `{d}` with the matching
permission prefix.

| Method | Path | Permission |
|---|---|---|
| GET | `/{dept}/tasks` | `{d}.read` |
| GET | `/{dept}/tasks/{id}` | `{d}.read` |
| POST | `/{dept}/tasks` | `{d}.manage` |
| PATCH | `/{dept}/tasks/{id}` | `{d}.manage` |
| POST | `/{dept}/tasks/{id}/progress` | `{d}.task.progress` **or** `{d}.manage` |
| GET | `/{dept}/summary` | `{d}.read` |
| GET | `/{dept}/schedules` | `{d}.read` |
| POST | `/{dept}/schedules` | `{d}.manage` |
| PATCH | `/{dept}/schedules/{id}` | `{d}.manage` |
| POST | `/{dept}/schedules/generate` | `{d}.manage` — idempotent |

`progress` accepts either grant because the *moves* are separated inside it: a
worker holding only `*.task.progress` can start and complete a task, while
`VERIFIED` and `CANCELLED` require `*.manage`. A Society Admin deliberately does
not hold the progress permission — completing a worker's task on their behalf
would make "who did this" a lie — but must still be able to sign one off.

`schedules/generate` runs the same code as the nightly worker and is safe to
call twice: `(schedule_id, due_on)` is unique, so a second run creates nothing.

### `/visitors` **[P5]**

| Method | Path | Permission |
|---|---|---|
| GET | `/visitors` | `visitor.read` — **owner-scoped** |
| GET | `/visitors/summary` | `security.read` |
| GET | `/visitors/{id}` | `visitor.read` |
| POST | `/visitors/pre-approvals` | `visitor.create` — returns a pass code |
| POST | `/visitors/gate-entries` | `visitor.create` — notifies the flat |
| POST | `/visitors/{id}/decision` | `visitor.approve` |
| POST | `/visitors/check-in` | `security.read` — by pass code |
| POST | `/visitors/{id}/check-in` | `security.read` |
| POST | `/visitors/{id}/check-out` | `security.read` |

The gate log moves forward only. A walk-up visitor starts at
`AWAITING_APPROVAL` and **cannot be checked in until the flat approves** —
attempting it is a 409. A denied visitor cannot be walked in at all; that takes
a fresh entry under whoever let them in.

A pass code identifies exactly one *live* pass. Once the visit ends the code is
free again, which keeps codes short enough to read out over a phone.

### `/security` **[P5]**

| Method | Path | Permission |
|---|---|---|
| GET | `/security/dashboard` | `security.read` — the whole gate screen in one call |
| GET | `/security/incidents` | `security.read` |
| GET | `/security/incidents/{id}` | `security.read` |
| POST | `/security/incidents` | `security.read` — a guard reports |
| PATCH | `/security/incidents/{id}` | `security.manage` — only a supervisor resolves |

### `/notices` **[P5]**

| Method | Path | Permission |
|---|---|---|
| GET | `/notices` | `notice.read` — filtered to the reader's audience |
| GET | `/notices/summary` | `notice.read` |
| GET | `/notices/{id}` | `notice.read` — **marks it read** |
| POST | `/notices` | `notice.manage` |
| PATCH | `/notices/{id}` | `notice.manage` |
| POST | `/notices/{id}/publication` | `notice.manage` — publish a draft now |
| POST | `/notices/{id}/read` | `notice.read` — idempotent |
| DELETE | `/notices/{id}` | `notice.manage` |

A reader sees society-wide notices, their own building's and block's, and their
owner/tenant group; staff see society-wide and staff-only. `read_count` is
returned as zero unless the caller holds `notice.manage` — who else opened the
AGM notice is not a neighbour's business.

A scheduled notice (`publish_at` in the future) is invisible to residents until
its moment, and returns **404** rather than 403 if its id is guessed.

### `/amenities` **[P5]**

| Method | Path | Permission |
|---|---|---|
| GET | `/amenities` | `amenity.read` |
| GET | `/amenities/{id}` | `amenity.read` |
| GET | `/amenities/{id}/availability?on=YYYY-MM-DD` | `amenity.read` |
| GET | `/amenities/summary` | `amenity.manage` |
| POST | `/amenities` | `amenity.manage` |
| PATCH | `/amenities/{id}` | `amenity.manage` |
| GET | `/amenities/bookings` | `amenity.read` — **owner-scoped** |
| POST | `/amenities/bookings` | `amenity.book` |
| POST | `/amenities/bookings/{id}/decision` | `amenity.manage` |
| POST | `/amenities/bookings/{id}/cancellation` | `amenity.book` |

`starts_at` must land on the amenity's slot boundary; an off-grid time is a
**422** naming the legal start times. Booking a slot somebody else took between
the availability call and the insert is a **409**, raised by a PostgreSQL
exclusion constraint rather than a check-then-insert — see
[tenant-schema.md](../database/tenant-schema.md).

`booked_by_flat` in an availability grid is `null` for a neighbour: they see
that a slot is taken, not who took it.

### `/notifications` **[P6]**

| Method | Path | Permission |
|---|---|---|
| GET | `/notifications` | `notification.read` |
| GET | `/notifications/feed` | `notification.read` — items and unread count together |
| POST | `/notifications/read` | `notification.read` |
| POST | `/notifications/read-all` | `notification.read` |
| GET | `/realtime/status` | `audit.read` — live socket counts for this worker |

There is no endpoint that *creates* a notification: one is always a side effect
of something else that happened.

Marking another user's notification read is not a 403 — the `user_id` predicate
simply matches nothing and the response says `marked: 0`, so the caller learns
nothing about whether the row exists.

### `/reports` **[P6]**

| Method | Path | Permission |
|---|---|---|
| GET | `/reports` | any of `report.read`, `billing.read_all` — **catalogue, filtered** |
| GET | `/reports/{key}` | per report |
| GET | `/reports/{key}/export` | per report — `text/csv`, `Cache-Control: no-store` |

Three endpoints for ten reports, because a report *is* data: every one returns
the same envelope of `columns`, `rows`, `totals` and `summary`, and the columns
carry a type (`money`, `number`, `percent`, `date`, `status`) that tells a
client how to render them. Adding a report touches no routing and needs no
client release.

**The catalogue is filtered by what the caller can actually run**, and a report
they cannot run returns **404**, not 403 — a menu item that 403s is a design
bug, and a 403 on a report key confirms the report exists.

Reports are gated only on society-wide permissions. An owner-scoped one such as
a resident's `payment.read` must never open this door, and an assertion at
import refuses to start the process if a report is ever registered against one.

`truncated: true` means the row cap was reached. A silently shortened defaulter
list is worse than no list.

### WebSocket **[P6]**

```
WS /api/v1/ws?token=<id-token>
```

The token is verified on connect and the connection is bound to the resolved
society — **the same guard chain as any HTTP request**: identity, account,
society status, subscription, tenant roles. A locked society or an expired
subscription is refused at the handshake, and there is no way to subscribe to
another society's stream because the room key is derived from the principal,
never from the request.

*Why a query parameter.* The browser WebSocket API cannot set an
`Authorization` header. The token is short-lived, the connection is TLS, and
the handshake URL is not logged with its query string in this deployment.

Frames are `{"type": ..., "data": {...}}`:

| `type` | Meaning |
|---|---|
| `connected` | Handshake acknowledged; carries the resolved `user_id`. |
| `ping` | Server keepalive every 25s, below any sane proxy's idle timeout. |
| `notification` | Something happened. Carries `category`, `title`, `body`, `link`. |

Close codes: **1008** for a missing, invalid or un-provisioned token (a platform
super admin has no society to subscribe to and is refused), **1011** for an
unexpected server failure.

**The socket carries no data the REST API does not.** Every event has a durable
row behind it, so a dropped connection costs freshness and nothing else — which
is why there is no replay, no sequence number and no acknowledgement. A client
that reconnects simply refetches `/notifications/feed`.

**Events are released on commit, never before.** A service queues an event on
its database session and SQLAlchemy's `after_commit` hook publishes it, so a
request that fails after queuing produces no notification for something that did
not happen.

A connection that falls too far behind is dropped rather than buffered
indefinitely: its queue is bounded at 100 events, and the durable rows are still
in PostgreSQL for its next page load.

## 5. Health

```
GET /health        liveness   — process is up
GET /health/ready  readiness  — central DB reachable, Firebase verifier initialised
GET /health/info   build/version metadata
```
Unauthenticated, excluded from rate limiting, and they never touch a tenant
database (a readiness probe must not open 50 tenant connections).

## 6. Rate limiting

In-process token bucket keyed by `firebase_uid` (falling back to client IP for
unauthenticated routes). No Redis in the MVP; the limiter is behind an interface
so a shared backend can be added when a second API instance appears.

| Scope | Limit |
|---|---|
| Unauthenticated | 20 / min / IP |
| Authenticated default | 300 / min / user |
| Write endpoints | 60 / min / user |
| Billing run trigger | 5 / hour / society |
| Formula validate/preview | 120 / min / user |
| File upload | 20 / hour / user |

429 responses carry `Retry-After` and `X-RateLimit-Remaining`.

## 7. Security headers & CORS

`Strict-Transport-Security`, `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`,
`Permissions-Policy` minimal, and a `Content-Security-Policy` on the API's own
doc routes.

CORS origins come from `CORS_ORIGINS` (explicit list). `allow_credentials` is
**false** — the app is token-based, not cookie-based, so wildcards and
credential leakage are both off the table.

## 8. Versioning

`/api/v1` is frozen once a mobile client ships. Additive changes (new optional
field, new endpoint) stay in v1. Breaking changes open `/api/v2` and v1 is
supported for a deprecation window with a `Deprecation` header.

The API is client-agnostic: no `/api/web/*`, no `/api/mobile/*`. Web and mobile
consume identical endpoints.

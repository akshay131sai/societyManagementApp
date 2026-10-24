# NestFlow

Multi-tenant society and apartment management SaaS for the Indian market.

**Modular monolith + database-per-society.** One FastAPI deployable, one React
SPA, and a physically separate PostgreSQL database for every society.

> **Status: Phases 1–6 complete.** Authentication, tenant isolation, automated
> society provisioning, RBAC, subscription locking, per-society theming, the
> full physical structure with residents and owner scoping, the dynamic billing
> engine and its visual formula builder, utilities and assets, the resident
> dashboard, operations (complaints, maintenance, housekeeping, security,
> visitors), community (notices, amenities), and the delivery layer —
> notifications over a WebSocket, ten reports with CSV export, and the nightly
> sweeps that keep them honest — are built, running and tested. **401 backend
> tests, 204 API operations**, every society route now a real screen.

---

## Quick start

**Prerequisites:** Python 3.12+, Node 20+, Docker (or a PostgreSQL 16+ you can
create databases on).

```bash
# 1. Database
docker compose -f infrastructure/docker-compose.yml up -d

# 2. Configuration
cp .env.example .env                 # backend
cp apps/web/.env.example apps/web/.env   # frontend (public values only)

# 3. Backend
cd apps/api
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows
# .venv/bin/python -m pip install -r requirements.txt       # macOS / Linux

.venv/Scripts/python -m alembic -c alembic.central.ini upgrade head
.venv/Scripts/python -m app.cli bootstrap --email you@example.com --name "Your Name"
.venv/Scripts/python run.py                                  # http://localhost:8000

# 4. Frontend (new terminal)
cd apps/web
npm install
npm run dev                                                  # http://localhost:5173
```

Sign in at <http://localhost:5173/login> with the email you passed to
`bootstrap`. No Firebase project is needed yet — see
[Development authentication](#development-authentication).

**API docs:** <http://localhost:8000/docs>

---

## What Phase 6 adds

The delivery layer: telling people things, proving what happened, and doing the
work nobody should have to remember to do.

- **A notification is published by a commit, not by a service.** Assigning a
  complaint writes a row, a timeline entry and a notification, then tells the
  assignee. If the request fails after that, the row is rolled back — and a
  toast for a ticket that does not exist is worse than no toast. So nothing
  publishes directly: services append to a per-session outbox and SQLAlchemy's
  `after_commit` hook releases it. `test_a_rolled_back_transaction_publishes_nothing`
  is the whole reason the outbox exists.
- **The socket carries nothing the REST API does not.** Every event has a
  durable row behind it, so a dropped connection costs freshness and nothing
  else — no replay, no sequence numbers, no acknowledgements. The `/ws`
  handshake runs the *same* guard chain as an HTTP request, so a locked society
  cannot keep receiving events by never reconnecting. A client that falls too
  far behind is dropped rather than buffered, and picks up its missed
  notifications from PostgreSQL on the next page load.
- **Ten reports, three endpoints.** A report *is* data: each returns the same
  envelope of `columns`, `rows`, `totals` and `summary`, with a type per column
  that tells the client how to render it. Adding "outstanding by building" is
  one function and one registry entry — no routing, no schema, no frontend
  release. The catalogue is filtered by what the caller can actually run, and a
  report they cannot run returns **404**, not 403.
- **The row cap is declared.** `truncated: true` when a report hits its limit.
  A silently shortened defaulter list is worse than no list.
- **Nightly sweeps that survive being restarted.** Task generation, notice
  publication, visitor-pass expiry, booking completion, complaint auto-close and
  escalation, booking reminders. Every job is idempotent, one society's failure
  is logged rather than aborting the sweep, and no job holds a business rule of
  its own — each calls the same service method the API calls. Any of them runs
  by hand with `python -m app.cli run-job <name>`.

Phase 6 also closed an authorization hole of its own. The reports module was
gated on `report.read` **or** `payment.read`, and a `FLAT_OWNER` holds
`payment.read` for their own bills — which let every resident open the society's
whole receipts report. Reports are now gated only on society-wide permissions,
and an assertion at import refuses to start the process if a report is ever
registered against an owner-scoped one.

## What Phase 5 adds

Operations and community — the six screens a society actually runs on.

- **A workflow is a table, not a chain of `if`s.** Complaints, tasks and
  visitors each move through a transition map checked before anything else
  happens, and an illegal move is a 409 naming the moves that *are* legal. The
  complaint detail response carries `allowed_transitions`, computed from that
  same map, so the client renders its buttons from the server's rules and
  cannot offer one that would be refused.
- **The ticket number is the database's job.** `complaints.ticket_number`
  defaults to an expression over a sequence, in IST, so two residents pressing
  Submit in the same millisecond cannot be handed the same number — and no
  service holds a lock to avoid it.
- **A slot cannot be double-booked.** Thirty people try to book the party lawn
  at 9 a.m. on a Sunday. The service checks the *rules* — advance limit, quota
  per flat, slot alignment — so a resident gets a sentence they can act on; the
  *race* is left entirely to a PostgreSQL `EXCLUDE USING gist` constraint over
  `(amenity_id, tstzrange)`, restricted to the statuses that actually hold a
  slot. A check-then-insert passes every test and loses every Sunday morning.
- **Maintenance and housekeeping are one implementation.** Identical workflows,
  separate permissions — so `department` tells them apart, and the API routes,
  the service and the React screen are each written once and mounted twice. Two
  copies would have drifted apart by the third bug fix.
- **A visitor cannot be walked in.** A walk-up starts at `AWAITING_APPROVAL`,
  the flat is notified, and check-in before approval is a 409. A denied visitor
  cannot be admitted at all; that takes a fresh entry under whoever let them in.
  Pass codes avoid `0/O` and `1/I/L` because a guard reads them off a phone.
- **A schedule is not a task.** `work_schedules` is the intention ("the lift is
  serviced monthly"); `work_tasks` is what happened on a given date. A skipped
  month is therefore *visible* rather than silently absent, and re-running the
  generator tops the day up instead of duplicating it — `(schedule_id, due_on)`
  is unique.
- **Owner scoping that understands common areas.** A resident's complaint list
  is their own flat's tickets *plus* the ones with no flat at all. Narrowing to
  `flat_id IN (…)` would hide the burst pipe in the lobby from the people
  walking past it.

## What Phase 4 adds

Utility metering, the shared assets a society tracks, and the screen a resident
actually opens the app for.

- **Meter readings that cannot lie.** `consumption` is a **generated column**,
  computed by PostgreSQL from the two readings. Nothing in the application
  calculates it, so a correction applied to one reading cannot leave a stale
  figure behind, and a client that posts its own `consumption` is ignored.
- **A meter cannot run backwards.** A `CHECK` refuses a reading below its
  opening value; the service refuses it earlier with a message about what to do
  when a meter has been replaced. A transposed entry is caught at the keyboard,
  not as a negative charge on a bill.
- **Bulk entry shaped like the job.** A meter reader walks a building once, so
  the screen is one date and one number per flat, each prefilled with the last
  round's closing value. A partially entered round can be re-run to top it up;
  a batch containing one bad row saves nothing.
- **One registration, one flat.** Vehicle plates are unique across the society
  among active vehicles — the gate must resolve a plate to exactly one flat.
  Removing a vehicle deactivates it (a gate log must still resolve) and frees
  the plate for whoever buys the car.
- **The resident dashboard.** One request assembles the whole screen: what is
  owed, when it is due, where the last bill's money went, and how water and
  electricity are trending. Eight round trips would be slow on a lift-lobby
  connection, and the numbers could disagree with each other; read in one
  transaction they cannot. At 390px the amount due is above the fold before a
  single chart has loaded.

Charts live in one module that nothing imports eagerly. Recharts is a 414 KB
chunk, and a resident who never opens an analytics screen never downloads it —
the entry bundle is unchanged at 169 KB (56 KB gzipped).

Phase 4 also closed a real authorization hole. `vehicle.manage` was listed as
broadening `vehicle.read` society-wide, and a `FLAT_OWNER` holds
`vehicle.manage` so they can register their own car — which meant every
resident could enumerate the society's whole vehicle and pet register, flat by
flat. Broadening is now transitive: a broadener lifts the scope only if the
holder's grant of *it* is itself society-wide. See
[RBAC §6](docs/architecture/rbac.md).

## What Phase 3 adds

The dynamic billing engine — the feature the product exists for.

- **Formulas are an AST, never a string.** A bill template's formula is a
  Pydantic discriminated union evaluated by a pure function. There is no
  `eval()` anywhere near billing, and no expression parser to escape from.
- **Money is `Decimal`, rounded `ROUND_HALF_UP`, and the total is the sum of
  the *rounded* line items** — so the printed rows add up to the printed total.
- **History is immutable.** Publishing a template version freezes it; database
  triggers refuse an `UPDATE` to a published version or to a published bill's
  amounts. A rate change creates version N+1 and last quarter's bills still
  recompute to exactly what the resident was charged.
- **"How was this calculated?"** Every bill stores its formula snapshot, its
  input snapshot and a step-by-step trace, so a resident gets a plain-language
  breakdown of their own bill rather than a number to argue about.

## What Phase 2 adds

Buildings → blocks → floors → flats → residents → family members, plus the two
things that make a 300-flat society usable rather than theoretical:

- **Bulk flat generation.** A block's flats are created from a numbering
  pattern (`{building}-{floor}{index:02d}` → `A-101 … A-1204`) in one call,
  with a dry-run preview and conflict detection. Onboarding a society is not
  300 dialogs.
- **Owner scoping.** A `FLAT_OWNER` holds `flat.read` but sees only their own
  flats — and a neighbour's flat returns **404, not 403**, so a resident cannot
  even confirm it exists. The narrowing is decided by
  `Principal.is_scoped_to_own()`, never by checking for a role, so a principal
  who also holds `flat.manage` is correctly not narrowed.

Three invariants are enforced by the database rather than by convention:

| Invariant | Enforced by |
|---|---|
| `flats.building_id` / `block_id` always match the flat's floor | `trg_flats_derive_parents` — derives them on insert/update, re-cascades when a floor moves |
| At most one active primary contact per flat | `ux_residents_primary`, a partial unique index |
| Flat numbers unique **per building** | `UNIQUE (building_id, flat_number)` — Tower A and Tower B can both have a "101" |

`flats.occupancy_status` is derived from who actually lives there
(`VACANT` / `OWNER_OCCUPIED` / `RENTED`), because a billing formula branches on
it and a stale value would bill the wrong branch.

## What Phase 1 does

```
SUPER ADMIN signs in
      ↓
FastAPI verifies the ID token
      ↓
Creates a society
      ↓  central record (societies, database_registry, admin, subscription)
      ↓  CREATE DATABASE nestflow_society_0001
      ↓  alembic upgrade head            (tenant migrations)
      ↓  seed roles, permissions, settings, default theme
      ↓  status → ACTIVE
      ↓
SOCIETY ADMIN signs in
      ↓  firebase_uid → platform_users → society_id   (server-side, always)
      ↓  society ACTIVE?  subscription valid?
      ↓  TenantDatabaseManager → that society's database
      ↓  roles and permissions read from the tenant tables
      ↓
Society dashboard, in that society's own theme
```

Every step of this is exercised by the test suite and by a scripted browser
walkthrough.

---

## Repository layout

```
apps/
  api/         FastAPI backend — the only thing that touches PostgreSQL
  web/         React 19 + Vite SPA
  mobile/      placeholder; the future React Native client uses the same API
packages/      shared types and generated API clients (empty until needed)
database/      per-database operational SQL and notes
infrastructure/ docker-compose for local PostgreSQL
docs/          architecture, database, API and deployment documentation
```

---

## Architecture

Read [docs/architecture/overview.md](docs/architecture/overview.md) first.

| Document | Covers |
|---|---|
| [overview.md](docs/architecture/overview.md) | Style, layering, module map, request lifecycle, scaling path |
| [tenant-isolation.md](docs/architecture/tenant-isolation.md) | Threat model, `TenantDatabaseManager`, provisioning saga, how it is tested |
| [authentication.md](docs/architecture/authentication.md) | Firebase/NestFlow split, principal resolution, guard ordering |
| [rbac.md](docs/architecture/rbac.md) | 9 roles, 90+ permissions, the full matrix |
| [billing.md](docs/architecture/billing.md) | Formula AST, slabs, versioning, immutable bill snapshots |
| [theme-system.md](docs/architecture/theme-system.md) | OKLCH token derivation, contrast safety, per-society isolation |
| [frontend-routes.md](docs/architecture/frontend-routes.md) | Route tree, guards, chunking strategy |
| [central-schema.md](docs/database/central-schema.md) | Platform database ERD and DDL |
| [tenant-schema.md](docs/database/tenant-schema.md) | Society database ERD and DDL |
| [api-contract.md](docs/api/api-contract.md) | Envelope, error codes, endpoint map |
| [deployment.md](docs/deployment/deployment.md) | Topology, sizing, backups, hardening checklist |

### The three rules that shape everything

1. **The tenant is never in the request.** No endpoint accepts a `societyId` in
   a body, query string or header. It is resolved from the authenticated
   principal, every request. The only exception is society *creation*.
2. **Firebase authenticates; NestFlow authorizes.** Custom claims are never
   read for access decisions, so a role change or a lock takes effect on the
   next request rather than the next hour.
3. **Money is computed server-side.** The Bill Builder is an editor; the
   backend formula engine is the authority, and `eval()` never touches a
   formula.

### RBAC changes need a sync

Runtime authorization reads the tenant *tables*, not `ROLE_PERMISSIONS`, so a
society provisioned before a permission change keeps the old grants. After
editing `app/core/permissions.py`, run:

```bash
python -m app.cli sync-rbac
```

It converges the tables on the code — adding new grants **and revoking removed
ones** — for system roles only, leaving any society-specific custom role alone.

---

## Development authentication

No Firebase project is required to run NestFlow locally. With
`AUTH_PROVIDER=dev`, the API accepts `dev:<email>` as a bearer token and the
login screen ignores the password field.

Three independent safeties keep this out of production:

1. `Settings` **raises at import** if `ENVIRONMENT=production` and
   `AUTH_PROVIDER=dev` — the process will not boot.
2. Startup logs a loud security banner whenever it is active.
3. `/auth/me` returns `auth_provider: "dev"`, and the UI shows a permanent
   `DEV AUTH` badge.

Switching to real Firebase is a `.env` change plus a service account. No
application code changes.

---

## Commands

### Backend (`apps/api`)

```bash
.venv/Scripts/python run.py                  # dev server (uses a Selector loop on Windows)
.venv/Scripts/python -m pytest               # full test suite

python -m app.cli bootstrap --email x@y.z    # default plans + a super admin
python -m app.cli list-societies             # societies, databases, schema revisions
python -m app.cli verify-tenant <uuid>       # inspect one tenant database
python -m app.cli migrate-tenants            # roll migrations across all societies
python -m app.cli migrate-tenants --dry-run
python -m app.cli sync-rbac                  # push a ROLE_PERMISSIONS change into existing societies
python -m app.cli expire-subscriptions

python -m app.cli run-job                    # list the scheduled jobs
python -m app.cli run-job generate-scheduled-work
python -m app.cli run-job close-stale-complaints --society-id <uuid>

alembic -c alembic.central.ini upgrade head
alembic -c alembic.tenant.ini -x database_name=nestflow_society_0001 upgrade head
```

### Frontend (`apps/web`)

```bash
npm run dev        # Vite dev server, proxies /api to :8000
npm run build      # production build + dist/stats.html bundle report
npx tsc -b         # type-check (strict mode)
```

---

## Testing

```bash
cd apps/api && .venv/Scripts/python -m pytest
```

401 integration tests against a real PostgreSQL — tenant isolation is a
property of how connections are routed, so testing it against mocks would prove
nothing. Two societies are provisioned once per session and dropped afterwards.

| Suite | Covers |
|---|---|
| `test_tenant_isolation.py` | **Mandatory.** Foreign `society_id` in body/query/header, cross-society reads, engine-cache correctness, DDL name allowlist |
| `test_auth.py` | Token failures, unregistered identities, guard ordering, security headers, production-config refusal |
| `test_rbac.py` | Matrix integrity, code↔database drift, privilege-escalation attempts, last-admin protection |
| `test_theme.py` | Per-society independence, CSS-injection-shaped inputs, reset |
| `test_provisioning.py` | Provisioning, Indian format validation, lock/unlock, subscription expiry and extension, audit redaction |
| `test_structure.py` | Buildings/blocks/floors/flats/residents, bulk generation and its guardrails, the derivation trigger, occupancy derivation, single-primary rule |
| `test_owner_scope.py` | **Mandatory.** Owner scoping, 404-not-403 for out-of-scope records, filters that must not widen scope, Phase 2 cross-society isolation |
| `test_ratelimit.py` | Sliding window, per-key independence, key pruning |
| `test_formula_engine.py` | AST evaluation, slab tariffs, Decimal policy, rounding, malformed formulas |
| `test_billing_periods.py` | Indian financial-year boundaries, period keys and labels, frequency arithmetic |
| `test_billing.py` | Templates, versioning, assignment resolution, billing runs, immutability triggers, payments, cross-society isolation |
| `test_utilities.py` | **Mandatory.** Generated consumption, monotonic meters, bulk-entry atomicity, asset uniqueness, resident dashboard scoping, and the regression that a resident's `*.manage` must not widen their `*.read` |
| `test_operations.py` | **Mandatory.** Complaint workflow (a ticket cannot skip to closed; a resident cannot mark their own ticket in progress), SLA targets by category and priority, internal notes invisible to residents, a worker who completes but cannot verify, idempotent task generation, a visitor who cannot be walked in, a pass that works once, cross-society isolation |
| `test_community.py` | **Mandatory.** Notice audience targeting (a building notice, an owners-only notice), read receipts counted once, scheduled notices invisible until their moment, the amenity slot grid, quota and advance limits, a snapshotted charge — and **two concurrent bookings of the same slot, where exactly one may win** |
| `test_notifications.py` | The realtime hub (per-tab delivery, no cross-society leak, a slow client dropped rather than buffered), the outbox (**a rolled-back transaction publishes nothing**), the feed badge matching the feed, socket handshake refusals, and every scheduled job run twice to prove it is idempotent |
| `test_reports.py` | Catalogue filtered by permission, a report you cannot run returning 404, the shared envelope asserted across all ten, CSV round-tripping its money, and figures that agree with the screens they summarise |

---

## Technology

| Layer | Choice | Why not something else |
|---|---|---|
| Backend | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic | One runtime for the API, the formula engine, the report builders and the nightly sweeps |
| Database | PostgreSQL 17, one database per society | Isolation becomes a connection-routing property, not a `WHERE` clause someone can forget |
| Auth | Firebase Authentication + Admin SDK | Identity is not worth building; authorization is, and stays in PostgreSQL |
| Frontend | React 19, Vite, TypeScript (strict), Redux Toolkit, React Hook Form, Tailwind v4, Radix | — |
| Theming | CSS custom properties derived in OKLCH | No theming library; perceptually uniform hover/subtle variants at every hue |
| Scheduling | APScheduler in-process | No Celery, no Redis. Eight short sweeps a day over warm tables did not justify a broker, a result backend and a worker fleet |
| Realtime | FastAPI WebSockets + an in-process hub | No Socket.IO, no Redis pub/sub. One deployable means a user's worker is the worker that reaches them; the durable row is in PostgreSQL either way |

Deliberately absent at this stage: Kubernetes, Redis, Kafka, Elasticsearch,
message brokers, microservices, a second UI framework.

---

## License

Proprietary.

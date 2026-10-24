# NestFlow — Architecture Overview

> Multi-tenant Society / Apartment Management SaaS for the Indian market.

## 1. Architectural style

**Modular monolith + database-per-tenant.**

One FastAPI deployable, internally partitioned into modules that own their own
routers, services, repositories and models. Each society (tenant) gets a
physically separate PostgreSQL database. No microservices, no message broker,
no Redis, no Kubernetes in the MVP.

The module boundary is the future service boundary: a module talks to another
module only through its **service** layer, never by importing another module's
repository or reaching into another module's tables. When a module has to be
extracted later, the service interface becomes the network interface.

```
        React Web (Vite SPA)          React Native (future)
                 |                              |
                 +--------------+---------------+
                                |
                     Firebase Authentication
                       (identity only)
                                |
                     Firebase ID Token (JWT)
                                |
                                v
                      +---------------------+
                      |   FastAPI /api/v1   |
                      |  (modular monolith) |
                      +----------+----------+
                                 |
                  +--------------+---------------+
                  |                              |
        Central PostgreSQL              TenantDatabaseManager
        (nestflow_platform)             (engine cache, per society)
                                                 |
                        +------------------------+------------------------+
                        |                        |                        |
                        v                        v                        v
              nestflow_society_001     nestflow_society_002     nestflow_society_003
```

## 2. Why database-per-society

| Concern | Outcome |
|---|---|
| Isolation | A tenant leak requires a *connection* bug, not a forgotten `WHERE society_id = ?`. Blast radius is bounded by the engine registry. |
| Compliance | Per-society backup, restore, export and hard-delete are one `pg_dump` / `DROP DATABASE`. |
| Noisy neighbour | One society's 40k-row billing run cannot bloat another's table statistics or index cache. |
| Migration risk | Tenant migrations roll forward society-by-society; a bad migration can be halted after society #3. |
| Cost | All tenant databases live on **one** PostgreSQL instance initially. Database-per-tenant is a schema decision, not a hardware decision. |

Trade-off accepted: cross-society analytics requires fan-out, and connection
count grows with tenant count. Both are addressed in section 6.

## 3. Layering

Business logic never lives in a router.

```
HTTP Request
   |
   v
Router            -- FastAPI path operation. Parses/validates, calls one service, returns.
   |                 Depends() supplies the authenticated principal + tenant session.
   v
Service           -- Application logic, transaction boundary, authorization decisions,
   |                 audit emission. The only layer another module may call.
   v
Domain / Engine   -- Pure logic. FormulaEngine, BillingEngine. No I/O, no session.
   |
   v
Repository        -- All SQL. Takes an AsyncSession, returns models/DTOs. No business rules.
   |
   v
SQLAlchemy 2.x (async) -> PostgreSQL
```

Rules enforced by review:

- A router imports **services** only.
- A service imports **repositories**, **engines** and other modules' **services**.
- A repository imports **models** only. It never decides *whether* something is allowed.
- Engines are pure functions over Pydantic models — unit-testable with no database.

## 4. Module map

| Module | Owns | Database |
|---|---|---|
| `platform` | societies, subscription plans, subscriptions, platform users, database registry | central |
| `auth` | token verification, principal resolution, RBAC evaluation | both |
| `provisioning` | tenant DB creation, tenant migration, seeding | both |
| `society` | buildings, blocks, floors, flats, residents, settings | tenant |
| `theme` | society theme settings | tenant |
| `billing` | templates, versions, runs, bills, line items | tenant |
| `utilities` | water and electricity readings | tenant |
| `assets` | parking slots, vehicles, pets | tenant |
| `operations` | complaints, work schedules and tasks, visitors, security incidents | tenant |
| `community` | notices, amenities, bookings | tenant |
| `payments` | payment records, provider abstraction | tenant |
| `notifications` | in-app rows, realtime fan-out | tenant |
| `reports` | the report registry, its builders and the CSV export | tenant |
| `workers` | the nightly sweeps: task generation, notice publication, pass expiry | both |

## 5. Request lifecycle

Every authenticated request resolves its tenant **server-side**. A client-supplied
`societyId` is never trusted — see [tenant-isolation.md](./tenant-isolation.md).

```
1.  RequestContextMiddleware   assign request_id, start timer
2.  Authorization: Bearer      extract Firebase ID token
3.  FirebaseVerifier           verify signature, audience, issuer, expiry -> firebase_uid
4.  PrincipalResolver          firebase_uid -> platform_user (central DB)
5.                             platform_user -> society_id (server-side, from membership)
6.  SocietyGuard               society.status must be ACTIVE
7.  SubscriptionGuard          subscription must be TRIAL or ACTIVE and not past end_date
8.  TenantDatabaseManager      society_id -> cached AsyncEngine -> AsyncSession
9.  PermissionGuard            required permission must be in principal.permissions
10. Router -> Service -> Repository
11. Envelope + audit + structured access log
```

Steps 3–9 are FastAPI dependencies, composed per-route. A route declares only
what it needs:

```python
@router.post("/societies")
async def create_society(
    body: SocietyCreate,
    principal: Principal = Depends(require_permission(Permission.SOCIETY_CREATE)),
    db: AsyncSession = Depends(get_central_session),
): ...
```

## 6. Scaling path (not implemented now, but not designed out)

| Pressure | Response |
|---|---|
| Connection count | `TenantDatabaseManager` uses a bounded LRU of engines with small per-tenant pools; idle engines are disposed. Next step is PgBouncer in transaction mode. |
| Read load | PostgreSQL read replica; repositories already take a session, so a `get_readonly_session` dependency is a drop-in. |
| Billing runs | `BillingEngine` is pure and already batched per run; moving it to a worker process is a scheduler change, not a logic change. |
| Cross-society reporting | Nightly rollup into a central metrics table, never live fan-out. |
| Module extraction | Service interfaces are the seam. Billing, notifications and realtime are the first candidates. |

## 7. Non-negotiable invariants

1. Firestore is never the primary datastore.
2. The tenant is derived from the authenticated principal, never from the request body/query/header.
3. Tenant data never lands in the central database.
4. Bills are immutable snapshots; template versions are append-only.
5. The backend formula engine is the sole authority for money. The frontend preview is advisory.
6. `eval()` / `exec()` never touch a formula.
7. Optional modules are lazy-loaded on the client; a Flat Owner never downloads the Bill Builder.
8. A workflow is a table, not a chain of `if`s. Every complaint, task and visitor status move is checked against a transition map before anything else happens.
9. A realtime event is published by a commit, never by a service. A rolled-back request produces no notification.

## 8. Realtime and scheduled work

Both arrived in Phase 6, and both are deliberately small.

**Realtime** is one in-process hub per worker, holding the WebSocket
connections that worker is serving. There is no broker: with a single
deployable, a fan-out that has to reach a user reaches them through the worker
they are connected to, and the notification row in PostgreSQL is the durable
record either way. The socket carries nothing the REST API does not, so a
dropped connection costs freshness and nothing else.

Events do not publish directly. A service appends to a per-session outbox and
SQLAlchemy's `after_commit` hook releases it, so the events reach the hub
exactly when the rows they describe become real — a request that fails after
queuing produces no notification for something that did not happen.

**Scheduled work** is APScheduler inside the API process. The jobs are a
handful of short sweeps a day over tables that are already warm; a broker, a
result backend and a worker fleet would be three more things to operate for no
gain. Every job is an ordinary coroutine taking a tenant session and returning
a count, so each is runnable from a test or from
`python -m app.cli run-job <name>` with no scheduler involved.

Three properties make the sweeps safe to restart:

1. **Every job is idempotent.** Running the whole set twice in one morning
   produces the same state as running it once.
2. **One society's failure is not another's.** Each society gets its own
   session; a failure is logged and the sweep continues.
3. **A job holds no business rules.** Each calls the same service method the
   API calls, so there is exactly one definition of "auto-close a resolved
   complaint".

`SCHEDULER_ENABLED=false` on every web worker but one — two processes running
the same sweep send every notification twice.

Both are scaling seams rather than scaling *solutions*. When a second worker
appears, the hub grows a Postgres `LISTEN`/`NOTIFY` bridge and the scheduler
moves to its own process; nothing above either interface changes.

## 9. Document index

| Document | Covers |
|---|---|
| [tenant-isolation.md](./tenant-isolation.md) | TenantDatabaseManager, provisioning, isolation proof |
| [authentication.md](./authentication.md) | Firebase boundary, principal resolution, guards |
| [rbac.md](./rbac.md) | Roles, permissions, full matrix |
| [billing.md](./billing.md) | Formula AST, engine, templates, versioning, snapshots |
| [theme-system.md](./theme-system.md) | CSS variable contract, per-society theming |
| [frontend-routes.md](./frontend-routes.md) | Route tree, code-splitting boundaries |
| [../database/central-schema.md](../database/central-schema.md) | Central ERD + DDL |
| [../database/tenant-schema.md](../database/tenant-schema.md) | Tenant ERD + DDL |
| [../api/api-contract.md](../api/api-contract.md) | Envelope, error codes, endpoint map |
| [../deployment/deployment.md](../deployment/deployment.md) | Topology, cost, operations |

# Tenant Isolation

This is the most important security property in NestFlow.
**Society A must never be able to read or write Society B's data.**

## 1. The threat model

The attacks we design against:

| # | Attack | Defence |
|---|---|---|
| T1 | Client sends `societyId` of another society in a body/query/header | The field does not exist in any request schema. Tenant is resolved from the principal. |
| T2 | Client sends `X-Society-Id` / `X-Tenant-Db` header | Ignored. No middleware reads a tenant header. |
| T3 | User is moved between societies but keeps an old token | Society is re-resolved from the central DB on **every** request, not baked into the token. |
| T4 | Forged Firebase custom claim carrying `society_id` | Custom claims are never read for authorization. |
| T5 | IDOR — valid `flat_id` from another society | Cross-society IDs cannot collide meaningfully because they live in different *databases*; a foreign id simply yields 404 in the caller's tenant DB. |
| T6 | SQL injection reaching another database | Repositories use bound parameters exclusively. Database names are validated against a strict pattern and never string-interpolated from user input. |
| T7 | Engine cache poisoning — wrong engine returned for a society | The cache key is the `society_id` UUID, and the resolved DSN is re-verified against `database_registry` on cache miss only. |
| T8 | Locked/expired society continues operating on a warm connection | Guards run before the session dependency, on every request. |

## 2. Where the tenant comes from

```
Authorization: Bearer <firebase-id-token>
        |
        v
verify_id_token()  ->  firebase_uid                (Firebase Admin SDK)
        |
        v
SELECT * FROM platform_users WHERE firebase_uid = :uid    (CENTRAL DB)
        |
        v
platform_user.society_id                            <-- THE ONLY SOURCE OF TRUTH
        |
        v
SELECT * FROM societies WHERE id = :society_id      (CENTRAL DB)
        |
        +--> status must be ACTIVE ................ else SOCIETY_LOCKED / SOCIETY_SUSPENDED
        |
        v
SELECT * FROM subscriptions WHERE society_id = :id AND is_current
        |
        +--> status in (TRIAL, ACTIVE) and end_date >= today ... else SUBSCRIPTION_EXPIRED
        |
        v
SELECT database_name, ... FROM database_registry WHERE society_id = :id
        |
        v
TenantDatabaseManager.get_session(society_id)  ->  AsyncSession bound to that DB
```

`SUPER_ADMIN` has `society_id IS NULL` and never receives a tenant session.
A super admin acting on a society does so through **central-DB** platform
endpoints (provisioning, subscription, lock/unlock) — not by impersonating a
tenant session.

## 3. TenantDatabaseManager

```python
class TenantDatabaseManager:
    async def get_session(self, society_id: UUID) -> AsyncIterator[AsyncSession]
    async def get_engine(self, society_id: UUID) -> AsyncEngine
    async def create_database(self, society_id: UUID, database_name: str) -> None
    async def run_migrations(self, society_id: UUID) -> str          # returns head revision
    async def drop_database(self, society_id: UUID) -> None          # archive/GDPR only
    async def dispose(self, society_id: UUID) -> None
    async def dispose_all(self) -> None
```

### Engine caching

One `AsyncEngine` per society, held in a bounded LRU (`TENANT_ENGINE_CACHE_SIZE`,
default 50). Each engine owns a small pool:

```
pool_size        = TENANT_POOL_SIZE        (default 2)
max_overflow     = TENANT_POOL_MAX_OVERFLOW(default 3)
pool_recycle     = 1800s
pool_pre_ping    = True
```

Worst case per API process: `50 * (2 + 3) = 250` connections. `max_connections`
on the instance is sized accordingly (see deployment doc). Evicting an LRU entry
disposes its engine so connections are returned, not leaked.

**A new connection is never created per request.** The per-request cost is
checking out a pooled connection.

### Database name safety

Tenant database names are **generated**, never accepted:

```
nestflow_society_{sequence:04d}     e.g. nestflow_society_0007
```

Before use in any DDL (`CREATE DATABASE` cannot be parameterised in PostgreSQL),
the name is validated against `^nestflow_society_[0-9]{4,10}$` and then quoted
with `psycopg.sql.Identifier`. A value failing the pattern raises before
touching the server.

## 4. Provisioning sequence

`CREATE DATABASE` cannot run inside a transaction block, so provisioning is a
saga with explicit compensation, not a single transaction.

```
1  BEGIN central tx
2    INSERT societies (status = PROVISIONING)
3    allocate sequence -> database_name
4    INSERT database_registry
5  COMMIT central tx                       <-- society is now durably PROVISIONING
6  CREATE DATABASE nestflow_society_000N    (autocommit connection to maintenance DB)
7  alembic upgrade head  (tenant config, -x database_name=...)
8  seed: permissions, roles, role_permissions
9  seed: default theme_settings, society_settings
10 create tenant `users` row for the society admin + assign SOCIETY_ADMIN
11 INSERT platform_users (society admin, firebase_uid) in central
12 INSERT subscriptions (TRIAL or chosen plan)
13 UPDATE societies SET status = ACTIVE
14 audit: SOCIETY_PROVISIONED
```

**Failure at any step** marks the society `PROVISIONING_FAILED`, records the
failing step and error in `database_registry.provisioning_error`, and leaves the
partial tenant database in place for inspection. Provisioning is **idempotent
and resumable**: re-running detects the existing database, skips `CREATE
DATABASE`, and continues from the first incomplete step. It never silently
half-succeeds into `ACTIVE`.

## 5. Guard ordering (why it matters)

```
require_authenticated        -> 401 UNAUTHENTICATED
require_known_user           -> 401 USER_NOT_REGISTERED
require_active_society       -> 403 SOCIETY_LOCKED | SOCIETY_SUSPENDED | SOCIETY_ARCHIVED
require_active_subscription  -> 402 SUBSCRIPTION_EXPIRED
tenant session               -> (only now is a tenant connection acquired)
require_permission(P)        -> 403 PERMISSION_DENIED
```

Society and subscription guards run **before** the tenant session dependency, so
a locked society never even opens a connection to its database. The permission
guard runs last so that "you are locked out" always wins over "you lack this
permission" — the more actionable message reaches the user.

## 6. How this is tested

`apps/api/tests/test_tenant_isolation.py` is a required, non-skippable suite.

| Test | Asserts |
|---|---|
| `test_two_societies_have_distinct_databases` | Registry rows differ; both databases exist. |
| `test_data_written_to_a_is_absent_in_b` | Insert a flat in A, list flats as a B user, assert absent. |
| `test_society_id_in_body_is_ignored` | POST with a foreign `society_id` field writes to the caller's tenant anyway. |
| `test_society_id_query_param_is_ignored` | Same for query string. |
| `test_tenant_header_is_ignored` | `X-Society-Id: <B>` as an A user still reads A. |
| `test_foreign_flat_id_returns_404` | A user GETs a real B flat UUID, receives 404 not 200. |
| `test_locked_society_is_refused` | Status LOCKED -> 403 `SOCIETY_LOCKED`, no tenant connection opened. |
| `test_expired_subscription_is_refused` | end_date in the past -> 402 `SUBSCRIPTION_EXPIRED`. |
| `test_engine_cache_returns_correct_database` | Interleaved A/B/A/B session requests each report their own `current_database()`. |
| `test_invalid_database_name_rejected` | Manager raises before issuing DDL for a name failing the pattern. |

## 7. Rules for contributors

1. Never add `society_id` to a request schema. If you think you need it, you
   need a super-admin platform endpoint instead.
2. Never pass a database name or DSN from the client. Ever.
3. Never call `TenantDatabaseManager.get_session()` with an id that did not come
   from `Principal.society_id`.
4. Never build SQL with f-strings. `text()` with bound parameters, or the ORM.
5. New tenant tables need no `society_id` column — the database *is* the scope.
   Adding one is a smell that the table belongs in the central DB.

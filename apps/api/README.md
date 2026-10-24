# NestFlow API

FastAPI backend. The only component that talks to PostgreSQL — the web and
mobile clients go through `/api/v1` without exception.

## Layout

```
app/
├── main.py              app assembly: middleware, handlers, routers, lifecycle
├── run.py (../)         dev entry point (Selector event loop on Windows)
├── cli.py               bootstrap, tenant migrations, diagnostics
│
├── api/
│   ├── deps.py          the guard chain — auth → society → subscription → session → permission
│   └── v1/              routers: health, auth, platform, society
│
├── core/
│   ├── config.py        Settings; refuses to construct in an unsafe combination
│   ├── errors.py        the full error taxonomy (code → HTTP status → message)
│   ├── permissions.py   Role and Permission enums + the RBAC matrix
│   ├── firebase.py      FirebaseTokenVerifier / DevTokenVerifier
│   ├── logging.py       structlog + a secret-redaction processor
│   ├── ratelimit.py     in-process sliding window
│   └── eventloop.py     SelectorEventLoop selection for psycopg on Windows
│
├── auth/
│   ├── principal.py     the immutable authenticated subject
│   └── resolver.py      firebase_uid → society → tenant session (the isolation hinge)
│
├── database/
│   ├── base.py          separate CentralBase / TenantBase metadata
│   ├── central.py       central engine + session factory
│   └── manager.py       TenantDatabaseManager — engines, DDL, migrations
│
├── models/{central,tenant}/
├── schemas/             Pydantic request/response models
├── repositories/        all SQL; no business rules
├── services/            application logic, transactions, audit
├── engines/{formula,billing}/   Phase 3 — pure, no I/O
└── workers/             Phase 3 — APScheduler jobs

migrations/{central,tenant}/    two independent Alembic histories
tests/
```

## Layering

```
Router → Service → Domain/Engine → Repository → SQLAlchemy → PostgreSQL
```

- A router imports **services** only.
- A service imports repositories, engines and other modules' **services**.
- A repository imports **models** only, and never decides *whether* something
  is allowed.
- Engines are pure functions — unit-testable with no database.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt

# Central schema, then default plans and a super admin
.venv/Scripts/python -m alembic -c alembic.central.ini upgrade head
.venv/Scripts/python -m app.cli bootstrap --email you@example.com --name "Your Name"

.venv/Scripts/python run.py
```

**Use `run.py`, not `uvicorn app.main:app`, on Windows.** psycopg's async mode
cannot run on the default `ProactorEventLoop`; `run.py` starts uvicorn with
`loop="none"` and creates a `SelectorEventLoop` explicitly. On Linux and macOS
the two are equivalent.

## Migrations

Two independent histories, because the central and tenant schemas evolve
separately.

```bash
# Central
alembic -c alembic.central.ini revision --autogenerate -m "add x"
alembic -c alembic.central.ini upgrade head

# One tenant
alembic -c alembic.tenant.ini -x database_name=nestflow_society_0001 upgrade head

# Every tenant, sequentially, halting on the first failure
python -m app.cli migrate-tenants --dry-run
python -m app.cli migrate-tenants
python -m app.cli list-societies          # which society is on which revision
```

Deploy order: **central migrations → application → tenant migrations.** Tenant
migrations must stay backward-compatible with the previous application version
for the length of a rollout.

Alembic does not autogenerate sequences; `society_db_seq` is maintained by hand
in the initial central migration.

## Testing

```bash
.venv/Scripts/python -m pytest
.venv/Scripts/python -m pytest tests/test_tenant_isolation.py -v
```

Integration tests against a real PostgreSQL. Two societies are provisioned once
per session and dropped afterwards. `test_tenant_isolation.py` must never be
skipped or marked xfail.

## Rules for contributors

1. **Never add `society_id` to a request schema.** If you think you need it,
   you need a super-admin platform endpoint instead.
2. **Never build SQL with f-strings.** Bound parameters or the ORM.
3. **Never call `TenantDatabaseManager.get_session()`** with an id that did not
   come from `Principal.society_id`.
4. **New tenant tables carry no `society_id` column** — the database is the
   scope. Wanting one means the table belongs in the central database.
5. **Business logic never goes in a router.**
6. **Never log a token, password or key.** The redaction filter is a backstop,
   not a licence.

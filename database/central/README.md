# database/central

Schema documentation lives in [docs/database/central-schema.md](../../docs/database/central-schema.md).

Migrations are Alembic and live with the application, so a schema change and
the code that needs it land in the same commit:

```
apps/api/migrations/central/
```

```bash
cd apps/api
alembic -c alembic.central.ini upgrade head
alembic -c alembic.central.ini revision --autogenerate -m "describe the change"
```

This directory holds ad-hoc SQL that is not part of the migration history —
operational queries, backfill scripts and reporting snippets.

# database/tenant

Schema documentation lives in [docs/database/tenant-schema.md](../../docs/database/tenant-schema.md).

Migrations live at `apps/api/migrations/tenant/` and are applied to **every**
society database:

```bash
cd apps/api

# One society
alembic -c alembic.tenant.ini -x database_name=nestflow_society_0001 upgrade head

# Every society, sequentially, halting on the first failure
python -m app.cli migrate-tenants
python -m app.cli migrate-tenants --dry-run
python -m app.cli list-societies      # shows which revision each society is on
```

## Writing a tenant migration

1. **No `society_id` column.** The database is the tenant boundary.
2. **Backward-compatible with the previous application version** for the
   duration of a rollout — expand/contract, never a breaking rename.
3. **Test against a scratch database first:**
   ```bash
   docker exec nestflow-postgres psql -U nestflow -d postgres -c "CREATE DATABASE nestflow_society_9999;"
   alembic -c alembic.tenant.ini -x database_name=nestflow_society_9999 upgrade head
   ```
4. Run `migrate-tenants --dry-run` before the real sweep.

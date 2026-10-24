# Deployment

> Design goal: run the MVP for roughly the cost of one small VM, on
> infrastructure that is boring, portable and AWS-compatible without being
> AWS-locked.

## 1. Target topology (MVP)

```
                     Internet
                        |
             +----------+----------+
             |                     |
      Static hosting          api.nestflow.in
      (CloudFront/S3,              |
       Netlify, Cloudflare)        |  HTTPS
             |                     v
      React SPA (dist/)     +--------------------+
                            |  Caddy / nginx     |  TLS termination, gzip/brotli
                            +---------+----------+
                                      |
                            +---------+----------+
                            |  uvicorn (FastAPI) |  systemd, 2 workers
                            |  + APScheduler     |  on exactly ONE worker
                            |  + WebSocket hub   |  per-worker, in process
                            +---------+----------+
                                      |
                            +---------+----------+
                            |   PostgreSQL 17    |  one instance
                            +--------------------+
                            | nestflow_platform  |
                            | nestflow_society_1 |
                            | nestflow_society_2 |
                            | nestflow_society_N |
                            +--------------------+
                                      |
                            +---------+----------+
                            | S3-compatible store|  logos, documents, photos
                            +--------------------+
```

One `t4g.small` (2 vCPU / 2 GB, ARM) runs API + Postgres comfortably for the
first ~20 societies. Static assets are served from a CDN, not the VM, so the box
only handles API traffic.

**Deliberately absent:** Kubernetes, ECS/EKS, Redis, Kafka, RabbitMQ,
Elasticsearch, NAT Gateway, load balancer, multiple API nodes, multiple DB
nodes. Each has a defined trigger for introduction (section 8) and none of them
are met at launch.

## 2. Why not managed Postgres on day one

RDS `db.t4g.micro` roughly doubles the monthly bill versus Postgres on the same
VM as the API. At MVP volumes the operational benefit (automated backups,
failover) is reproducible with `pg_dump` to object storage plus a documented
restore drill. The move to RDS is a connection-string change — nothing in the
application assumes a co-located database.

## 3. Sizing

`max_connections` must cover the tenant engine cache:

```
API workers               2
engine cache per worker  50   (TENANT_ENGINE_CACHE_SIZE)
pool per engine           5   (pool_size 2 + max_overflow 3)
central pool per worker  10
                        ----
worst case          2 * (50*5 + 10) = 520
```

Set `max_connections = 200` and `TENANT_ENGINE_CACHE_SIZE = 15` for a 2 GB box —
`2 * (15*5 + 10) = 170`. LRU eviction disposes engines, so exceeding 15 active
societies costs a reconnect, not an error. Revisit at ~40 societies by
introducing PgBouncer in transaction mode rather than by growing the pool.

```
shared_buffers      = 512MB
effective_cache_size= 1GB
work_mem            = 8MB
maintenance_work_mem= 128MB
max_connections     = 200
```

## 4. Environments

| | Development | Staging | Production |
|---|---|---|---|
| `ENVIRONMENT` | `development` | `staging` | `production` |
| Auth | `AUTH_PROVIDER=dev` allowed | firebase | **firebase enforced** |
| Postgres | Docker `nestflow-postgres:5433` | managed/VM | VM or RDS |
| Storage | local filesystem | S3 bucket | S3 bucket |
| Logs | pretty console | JSON | JSON -> CloudWatch/Loki |
| Docs (`/docs`) | on | on | **off** |
| Debug errors | on | off | off |

`Settings` refuses to construct if `ENVIRONMENT=production` and
`AUTH_PROVIDER=dev`, or if any secret is left at its example value. The process
fails to start rather than starting insecurely.

## 5. Migrations

Two Alembic configurations:

```
apps/api/migrations/central/     -> nestflow_platform
apps/api/migrations/tenant/      -> every nestflow_society_*
```

```bash
# central
alembic -c alembic.central.ini upgrade head

# one tenant
alembic -c alembic.tenant.ini -x database_name=nestflow_society_0001 upgrade head

# all tenants, sequentially, halting on first failure
python -m app.cli migrate-tenants
python -m app.cli migrate-tenants --dry-run
python -m app.cli migrate-tenants --society-id <uuid>
```

`migrate-tenants` records the applied head in
`database_registry.alembic_revision`, so drift between societies is visible in
one central query — which matters, because "which societies are on which
revision" is otherwise unanswerable in a database-per-tenant design.

Deploy order: **central migrations → application → tenant migrations.** Tenant
migrations must be backward-compatible with the previous application version for
the duration of the rollout (expand/contract: add nullable column, deploy,
backfill, deploy, drop in a later release).

## 6. Deploy sequence

```bash
git pull --ff-only
python -m pip install -r apps/api/requirements.txt
alembic -c alembic.central.ini upgrade head
systemctl restart nestflow-api          # uvicorn behind Caddy
python -m app.cli migrate-tenants
curl -fsS localhost:8000/health/ready
```

Frontend:
```bash
npm --prefix apps/web ci
npm --prefix apps/web run build          # emits dist/ + stats.html
# sync dist/ to the CDN origin, invalidate
```

Zero-downtime is not a launch requirement; a ~5 second restart at a low-traffic
hour is acceptable and avoids a load balancer. When it becomes one, run two
uvicorn sockets behind Caddy and restart them alternately — at which point the
APScheduler instance must be elected via a PostgreSQL advisory lock (noted in
[billing.md](../architecture/billing.md) section 9).

## 7. Backup & recovery

```bash
pg_dumpall --globals-only            > globals.sql
pg_dump -Fc nestflow_platform        > platform.dump
# per society, so one tenant can be restored without touching the others
pg_dump -Fc nestflow_society_0001    > society_0001.dump
```

Nightly cron, uploaded to object storage, 30 daily + 12 monthly retained.

Per-society restore is the point of this schema design:
```bash
createdb nestflow_society_0001_restore
pg_restore -d nestflow_society_0001_restore society_0001.dump
```
No other society is affected, and GDPR-style erasure is `DROP DATABASE`.

**A backup that has never been restored is not a backup** — a quarterly restore
drill into a scratch database is part of the runbook, not an aspiration.

## 8. When to add infrastructure

| Signal | Change |
|---|---|
| p95 API latency > 500 ms with CPU headroom | Profile queries first; add indexes |
| Sustained CPU > 70% | Vertical scale the VM |
| > 40 active societies | PgBouncer (transaction mode) |
| > 100 societies | Move Postgres to its own instance / RDS |
| Two API instances needed | Advisory-lock scheduler election, shared rate limiter |
| Billing runs blocking request latency | Extract billing to a worker process |
| Multi-region residents | Read replica + CDN for API GETs |

Nothing on this list is adopted preemptively.

## 9. Monitoring

MVP: structured JSON logs (`request_id`, `firebase_uid`, `society_id`, endpoint,
status, duration) shipped to CloudWatch or Loki, plus uptime checks on
`/health/ready`.

Alert on: readiness failing 2 consecutive checks, 5xx rate > 1% over 5 min,
p95 > 1 s over 10 min, disk > 80%, connection count > 80% of `max_connections`,
any `PROVISIONING_FAILED` society, any failed billing run.

## 10. Production hardening checklist

- [ ] `ENVIRONMENT=production`, `AUTH_PROVIDER=firebase`, `DEBUG=false`
- [ ] `/docs` and `/redoc` disabled
- [ ] Firebase service account from a secret manager, not a file in the repo
- [ ] Application DB role is **not** superuser. A separate
      `nestflow_provisioner` role holds `CREATEDB` and is used only by the
      provisioning path
- [ ] Postgres listens on localhost only (or a private subnet + SG)
- [ ] `REVOKE UPDATE, DELETE ON platform_audit_logs, audit_logs FROM nestflow_app`
- [ ] TLS via Caddy/ACME, HSTS on, HTTP redirected
- [ ] `CORS_ORIGINS` is an explicit list — no wildcard
- [ ] Rate limiting enabled
- [ ] Nightly backups verified by a restore drill
- [ ] Log redaction filter confirmed against a token-bearing request
- [ ] `.env` is `chmod 600`, never committed
- [ ] Object storage bucket is private; assets served via signed URLs
- [ ] `SCHEDULER_ENABLED=true` on **exactly one** worker and `false` on the
      rest — two processes running the same nightly sweep send every
      notification twice
- [ ] The reverse proxy passes WebSocket upgrades through to `/api/v1/ws`, and
      its idle timeout is above 25 seconds (the server's heartbeat interval)
- [ ] Access logs do **not** record query strings, or `/api/v1/ws` is excluded
      from them — the socket handshake carries its token there because the
      browser WebSocket API cannot set a header

## 11. Portability

Nothing above is AWS-specific by contract:

| Concern | Interface | AWS | Alternative |
|---|---|---|---|
| Compute | Linux + systemd | EC2 | Hetzner, DigitalOcean, Lightsail |
| Database | PostgreSQL 16+ | RDS | Neon, Supabase, self-hosted |
| Objects | S3 API | S3 | Cloudflare R2, MinIO, Backblaze B2 |
| Static | any CDN | CloudFront | Netlify, Cloudflare Pages |
| Logs | stdout JSON | CloudWatch | Loki, Datadog |

`StorageProvider` is an interface with `LocalStorage` and `S3Storage`
implementations; no `boto3` import exists outside `app/services/storage/s3.py`.

## 12. Scheduled work and realtime

Both live inside the API process. Neither is a separate deployable, and both
have a documented seam for the day that changes.

### The sweeps

| IST | Job | What it does |
|---|---|---|
| 01:00 | `expire-subscriptions` | Marks past-due subscriptions EXPIRED (central DB) |
| 02:00 | `expire-visitor-passes` | Closes out pre-approvals nobody used |
| 02:15 | `complete-past-bookings` | Retires bookings whose slot has ended |
| 06:00 | `publish-due-notices` | Publishes notices whose scheduled moment arrived |
| 06:15 | `generate-scheduled-work` | Raises today's maintenance and housekeeping tasks |
| 06:30 | `close-stale-complaints` | Closes resolved tickets nobody came back to |
| 10:00 | `escalate-overdue-complaints` | Tells managers what has passed its target |
| 18:00 | `remind-upcoming-bookings` | Nudges residents whose booking is tomorrow |

The clock is `Asia/Kolkata`, because a society's day starts and ends there.
Jobs never overlap (`max_instances=1`), a process that was asleep runs each
missed job once rather than N times (`coalesce=True`), and a job more than an
hour late is skipped in favour of tomorrow's run.

Run one by hand — against every society, or one:

```bash
python -m app.cli run-job                       # list them
python -m app.cli run-job generate-scheduled-work
python -m app.cli run-job close-stale-complaints --society-id <uuid>
```

`GET /health/info` reports whether this worker is running the scheduler and
when each job next fires, so "which box owns the sweeps" is answerable from
outside.

### The socket

`GET /health/info` also reports this worker's live connection count, and
`GET /api/v1/realtime/status` (needs `audit.read`) breaks it down per society.
Both are **per-worker** figures — with two workers behind a proxy, a user is
connected to one of them and the numbers will not agree. That is expected, and
it is also the trigger for the next step: when a second worker matters, the hub
grows a Postgres `LISTEN`/`NOTIFY` bridge so a fan-out on worker A reaches a
socket on worker B. Nothing above the hub interface changes.

Until then, a notification never depends on the socket to arrive: the row is
written in the same transaction as the thing that caused it, and a client that
missed the push sees it on its next `/notifications/feed`.

import { Activity, Clock, Database, RefreshCw, ShieldAlert, Wifi } from "lucide-react";
import * as React from "react";

import { NFStatCard } from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFPageHeader,
  NFSkeleton,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { ApiError, api } from "@/services/api";
import { formatDateTime, formatNumber } from "@/utils/format";

interface SchedulerJob {
  id: string;
  next_run: string | null;
}

interface BuildInfo {
  name: string;
  version: string;
  environment: string;
  api_prefix: string;
  auth_provider: string;
  locale: string;
  currency: string;
  timezone: string;
  scheduler: { running: boolean; timezone: string; jobs: SchedulerJob[] };
  realtime_connections: number;
}

interface Readiness {
  status: string;
  central_database: string;
  auth_provider: string;
  tenant_engines_cached: number;
  checks_passed: boolean;
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-[var(--nf-border)] py-2.5 last:border-0">
      <dt className="text-[13px] text-[var(--nf-text-muted)]">{label}</dt>
      <dd className="text-right text-[13px] font-medium text-[var(--nf-text)]">{value}</dd>
    </div>
  );
}

export default function PlatformSettingsPage() {
  const [info, setInfo] = React.useState<BuildInfo | null>(null);
  const [ready, setReady] = React.useState<Readiness | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [i, r] = await Promise.all([
        api.get<BuildInfo>("/health/info"),
        api.get<Readiness>("/health/ready"),
      ]);
      setInfo(i);
      setReady(r);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not read platform status.");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  // Development auth accepts any `dev:<email>` token. Saying so loudly here is
  // the whole point of this screen existing in a deployed environment.
  const devAuth = info?.auth_provider === "dev";

  return (
    <>
      <NFPageHeader
        title="Platform Settings"
        description="Runtime configuration and health for this API process. These values come from the server's environment — change them there, not here."
        actions={
          <NFButton variant="secondary" onClick={() => void load()} loading={loading}>
            <RefreshCw /> Refresh
          </NFButton>
        }
      />

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/25 bg-[var(--nf-danger-subtle)] px-4 py-3 text-sm text-[var(--nf-danger)]"
        >
          {error}
        </div>
      )}

      {devAuth && (
        <div
          role="alert"
          className="mb-4 flex items-start gap-3 rounded-[var(--nf-radius-sm)] border border-[var(--nf-warning)]/25 bg-[var(--nf-warning-subtle)] px-4 py-3 text-sm text-[var(--nf-warning)]"
        >
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p>
            <span className="font-semibold">Development authentication is active.</span> Any{" "}
            <code className="font-mono">dev:&lt;email&gt;</code> bearer token is accepted without a
            credential check. Set <code className="font-mono">AUTH_PROVIDER=firebase</code> before
            exposing this service.
          </p>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <NFStatCard
          label="Readiness"
          value={ready?.status ?? "—"}
          icon={<Activity />}
          tone={ready?.checks_passed ? "success" : "danger"}
          hint={ready?.checks_passed ? "All checks passed" : "One or more checks failed"}
          loading={loading}
        />
        <NFStatCard
          label="Central database"
          value={ready?.central_database ?? "—"}
          icon={<Database />}
          tone={ready?.central_database === "ok" ? "success" : "danger"}
          hint="Platform registry connection"
          loading={loading}
        />
        <NFStatCard
          label="Tenant engines cached"
          value={formatNumber(ready?.tenant_engines_cached ?? 0)}
          icon={<Database />}
          tone="info"
          hint="Society connection pools held open"
          loading={loading}
        />
        <NFStatCard
          label="Realtime connections"
          value={formatNumber(info?.realtime_connections ?? 0)}
          icon={<Wifi />}
          tone="primary"
          hint="Live sockets on this worker"
          loading={loading}
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <NFCard>
          <NFCardHeader title="Build" description="What this process is running." />
          <NFCardBody>
            {loading && !info ? (
              <NFSkeleton className="h-40 w-full" />
            ) : (
              <dl>
                <Row label="Application" value={info?.name ?? "—"} />
                <Row label="Version" value={info?.version ?? "—"} />
                <Row
                  label="Environment"
                  value={
                    info ? (
                      <NFStatusBadge
                        status={info.environment.toUpperCase()}
                        tone={info.environment === "production" ? "success" : "info"}
                      />
                    ) : (
                      "—"
                    )
                  }
                />
                <Row
                  label="API prefix"
                  value={<span className="font-mono">{info?.api_prefix ?? "—"}</span>}
                />
                <Row
                  label="Auth provider"
                  value={
                    info ? (
                      <NFStatusBadge
                        status={info.auth_provider.toUpperCase()}
                        tone={devAuth ? "warning" : "success"}
                      />
                    ) : (
                      "—"
                    )
                  }
                />
              </dl>
            )}
          </NFCardBody>
        </NFCard>

        <NFCard>
          <NFCardHeader title="Regional" description="Defaults applied to new societies." />
          <NFCardBody>
            {loading && !info ? (
              <NFSkeleton className="h-40 w-full" />
            ) : (
              <dl>
                <Row label="Locale" value={info?.locale ?? "—"} />
                <Row label="Currency" value={info?.currency ?? "—"} />
                <Row label="Timezone" value={info?.timezone ?? "—"} />
                <Row label="Scheduler timezone" value={info?.scheduler.timezone ?? "—"} />
                <Row
                  label="Scheduler"
                  value={
                    info ? (
                      <NFStatusBadge
                        status={info.scheduler.running ? "RUNNING" : "STOPPED"}
                        tone={info.scheduler.running ? "success" : "danger"}
                      />
                    ) : (
                      "—"
                    )
                  }
                />
              </dl>
            )}
          </NFCardBody>
        </NFCard>
      </div>

      <NFCard className="mt-4">
        <NFCardHeader
          title="Background jobs"
          description="Sweeps this worker owns — expiring passes, publishing due notices, escalating overdue complaints."
        />
        <NFCardBody>
          {loading && !info ? (
            <NFSkeleton className="h-32 w-full" />
          ) : info && info.scheduler.jobs.length > 0 ? (
            <ul className="divide-y divide-[var(--nf-border)]">
              {info.scheduler.jobs.map((job) => (
                <li key={job.id} className="flex items-center justify-between gap-4 py-2.5">
                  <span className="flex min-w-0 items-center gap-2 text-[13px] text-[var(--nf-text)]">
                    <Clock className="size-3.5 shrink-0 text-[var(--nf-text-subtle)]" aria-hidden />
                    <span className="truncate font-mono">{job.id}</span>
                  </span>
                  <span className="shrink-0 text-[13px] tabular-nums text-[var(--nf-text-muted)]">
                    {job.next_run ? formatDateTime(job.next_run) : "Not scheduled"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-2 text-[13px] text-[var(--nf-text-muted)]">
              No scheduled jobs are registered on this worker.
            </p>
          )}
        </NFCardBody>
      </NFCard>
    </>
  );
}

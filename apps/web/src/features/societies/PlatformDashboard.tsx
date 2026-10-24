import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  CreditCard,
  Lock,
  Package,
  Plus,
  Users,
} from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";

import { NFStatCard } from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFEmptyState,
  NFPageHeader,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { api } from "@/services/api";
import type { Page } from "@/services/api";
import type { PlatformDashboard as Dashboard, Society } from "@/types";
import { formatDate, formatNumber } from "@/utils/format";

export default function PlatformDashboardPage() {
  const [stats, setStats] = React.useState<Dashboard | null>(null);
  const [recent, setRecent] = React.useState<Society[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const [dashboard, societies] = await Promise.all([
          api.get<Dashboard>("/platform/dashboard", undefined, controller.signal),
          api.get<Page<Society>>("/platform/societies", { limit: 5 }, controller.signal),
        ]);
        setStats(dashboard);
        setRecent(societies.items);
      } catch (e) {
        if ((e as Error).name !== "AbortError") {
          setError((e as Error).message);
        }
      } finally {
        setLoading(false);
      }
    })();
    return () => controller.abort();
  }, []);

  return (
    <>
      <NFPageHeader
        title="Platform overview"
        description="Every society, subscription and platform user across NestFlow."
        actions={
          <NFButton asChild>
            <Link to="/admin/societies/new">
              <Plus /> New society
            </Link>
          </NFButton>
        }
      />

      {error && (
        <div
          role="alert"
          className="mb-6 rounded-[var(--nf-radius)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] p-4 text-sm text-[var(--nf-text)]"
        >
          {error}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <NFStatCard
          label="Total societies"
          value={formatNumber(stats?.total_societies ?? 0)}
          icon={<Building2 />}
          loading={loading}
        />
        <NFStatCard
          label="Active"
          value={formatNumber(stats?.active_societies ?? 0)}
          icon={<CheckCircle2 />}
          tone="success"
          loading={loading}
        />
        <NFStatCard
          label="Locked or suspended"
          value={formatNumber(stats?.locked_societies ?? 0)}
          icon={<Lock />}
          tone="danger"
          loading={loading}
        />
        <NFStatCard
          label="Active subscriptions"
          value={formatNumber(stats?.active_subscriptions ?? 0)}
          icon={<CreditCard />}
          tone="info"
          hint={
            stats?.expiring_soon
              ? `${stats.expiring_soon} expiring within 30 days`
              : "None expiring soon"
          }
          loading={loading}
        />
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <NFStatCard
          label="Platform users"
          value={formatNumber(stats?.total_users ?? 0)}
          icon={<Users />}
          loading={loading}
        />
        <NFStatCard
          label="Subscription plans"
          value={formatNumber(stats?.total_plans ?? 0)}
          icon={<Package />}
          loading={loading}
        />
        <NFStatCard
          label="Provisioning"
          value={formatNumber(stats?.provisioning_societies ?? 0)}
          icon={<Building2 />}
          tone="info"
          loading={loading}
        />
        <NFStatCard
          label="Setup failed"
          value={formatNumber(stats?.failed_societies ?? 0)}
          icon={<AlertTriangle />}
          tone={stats?.failed_societies ? "danger" : "success"}
          hint={stats?.failed_societies ? "Needs attention" : "All healthy"}
          loading={loading}
        />
      </div>

      <NFCard className="mt-6">
        <NFCardHeader
          title="Recently added societies"
          action={
            <NFButton variant="ghost" size="sm" asChild>
              <Link to="/admin/societies">View all</Link>
            </NFButton>
          }
        />
        {recent.length === 0 && !loading ? (
          <NFEmptyState
            icon={<Building2 />}
            title="No societies yet"
            description="Create the first society to get started. Its database is provisioned automatically."
            action={
              <NFButton asChild>
                <Link to="/admin/societies/new">
                  <Plus /> Create a society
                </Link>
              </NFButton>
            }
          />
        ) : (
          <NFCardBody className="divide-y divide-[var(--nf-border)] p-0">
            {recent.map((society) => (
              <Link
                key={society.id}
                to={`/admin/societies/${society.id}`}
                className="flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-[var(--nf-primary-subtle)]"
              >
                <span
                  className="flex size-9 shrink-0 items-center justify-center rounded-[var(--nf-radius-sm)] bg-[var(--nf-primary-subtle)] text-[var(--nf-primary)]"
                  aria-hidden
                >
                  <Building2 className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-[var(--nf-text)]">
                    {society.name}
                  </p>
                  <p className="truncate text-xs text-[var(--nf-text-muted)]">
                    {society.city}, {society.state} · added {formatDate(society.created_at)}
                  </p>
                </div>
                <NFStatusBadge status={society.status} />
              </Link>
            ))}
          </NFCardBody>
        )}
      </NFCard>
    </>
  );
}

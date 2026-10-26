import { KeyRound, ShieldCheck, Users } from "lucide-react";
import * as React from "react";

import { NFDataTable, NFPagination, NFSearch, type Column } from "@/components/nestflow/data";
import {
  NFAvatar,
  NFButton,
  NFCard,
  NFEmptyState,
  NFPageHeader,
  NFSelect,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { SetPasswordDialog } from "@/features/auth/passwords";
import { ApiError, api, type Page } from "@/services/api";
import { IS_PASSWORD_AUTH } from "@/services/auth";
import type { PlatformUser, Society } from "@/types";
import { formatDateTime, formatPhone, formatRelative } from "@/utils/format";

export default function PlatformUsersPage() {
  const [data, setData] = React.useState<Page<PlatformUser> | null>(null);
  const [societies, setSocieties] = React.useState<Society[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [societyId, setSocietyId] = React.useState("");
  const [debouncedQ, setDebouncedQ] = React.useState("");
  const [passwordFor, setPasswordFor] = React.useState<PlatformUser | null>(null);

  React.useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQ(q);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  // The society filter needs names, and the list endpoint only returns ids.
  React.useEffect(() => {
    void api
      .get<Page<Society>>("/platform/societies", { page: 1, limit: 100 })
      .then((p) => setSocieties(p.items))
      .catch(() => setSocieties([]));
  }, []);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api
      .get<Page<PlatformUser>>(
        "/platform/users",
        { page, limit: 25, q: debouncedQ, society_id: societyId },
        controller.signal,
      )
      .then((p) => {
        setData(p);
        setError(null);
      })
      .catch((e) => {
        if ((e as Error).name === "AbortError") return;
        setError(e instanceof ApiError ? e.message : "Could not load platform users.");
        setData(null);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, debouncedQ, societyId]);

  const societyName = React.useCallback(
    (id: string | null) => societies.find((s) => s.id === id)?.name ?? null,
    [societies],
  );

  const columns: Column<PlatformUser>[] = [
    {
      key: "user",
      header: "User",
      render: (u) => (
        <div className="flex min-w-0 items-center gap-3">
          <NFAvatar name={u.display_name} />
          <div className="min-w-0">
            <p className="truncate font-medium text-[var(--nf-text)]">{u.display_name}</p>
            <p className="truncate text-xs text-[var(--nf-text-muted)]">{u.email}</p>
          </div>
        </div>
      ),
    },
    {
      key: "scope",
      header: "Scope",
      render: (u) =>
        u.is_super_admin ? (
          <span className="inline-flex items-center gap-1.5 text-[13px] font-medium text-[var(--nf-primary)]">
            <ShieldCheck className="size-4" aria-hidden /> Super admin
          </span>
        ) : (
          <span className="text-[13px] text-[var(--nf-text-muted)]">
            {societyName(u.society_id) ?? "Society member"}
          </span>
        ),
    },
    {
      key: "phone",
      header: "Phone",
      hideOnMobile: true,
      render: (u) => (
        <span className="text-[var(--nf-text-muted)] tabular-nums">
          {u.phone ? formatPhone(u.phone) : "—"}
        </span>
      ),
    },
    {
      key: "last_login",
      header: "Last sign-in",
      hideOnMobile: true,
      render: (u) => (
        <span className="text-[var(--nf-text-muted)]" title={formatDateTime(u.last_login_at)}>
          {u.last_login_at ? formatRelative(u.last_login_at) : "Never"}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (u) => <NFStatusBadge status={u.is_active ? "ACTIVE" : "SUSPENDED"} />,
    },
    ...(IS_PASSWORD_AUTH
      ? [
          {
            key: "actions",
            header: "",
            className: "text-right",
            render: (u: PlatformUser) => (
              <NFButton variant="ghost" size="sm" onClick={() => setPasswordFor(u)}>
                <KeyRound /> Set password
              </NFButton>
            ),
          },
        ]
      : []),
  ];

  return (
    <>
      <NFPageHeader
        title="Platform Users"
        description="Every account that can sign in — super admins and each society's members. Society roles are managed inside the society itself."
      />

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/25 bg-[var(--nf-danger-subtle)] px-4 py-3 text-sm text-[var(--nf-danger)]"
        >
          {error}
        </div>
      )}

      <NFCard>
        <div className="flex flex-wrap items-center gap-3 border-b border-[var(--nf-border)] p-4">
          <NFSearch value={q} onChange={setQ} placeholder="Search by name or email…" />
          <NFSelect
            value={societyId}
            onChange={(e) => {
              setSocietyId(e.target.value);
              setPage(1);
            }}
            aria-label="Filter by society"
            className="sm:w-56"
          >
            <option value="">All societies</option>
            {societies.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </NFSelect>
        </div>

        <NFDataTable
          caption="Platform user accounts"
          columns={columns}
          rows={data?.items ?? []}
          rowKey={(u) => u.id}
          loading={loading}
          empty={
            <NFEmptyState
              icon={<Users />}
              title={q || societyId ? "No matching users" : "No users yet"}
              description={
                q || societyId
                  ? "Try a different search term or clear the society filter."
                  : "Accounts appear here once a society is provisioned with its first administrator."
              }
            />
          }
        />

        {data && (
          <NFPagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            limit={data.limit}
            onPageChange={setPage}
          />
        )}
      </NFCard>

      {passwordFor && (
        <SetPasswordDialog
          open
          onOpenChange={(o) => !o && setPasswordFor(null)}
          endpoint={`/platform/users/${passwordFor.id}/password`}
          name={passwordFor.display_name}
          email={passwordFor.email}
        />
      )}
    </>
  );
}

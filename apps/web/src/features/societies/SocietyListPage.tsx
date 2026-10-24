import { Building2, Plus } from "lucide-react";
import * as React from "react";
import { Link, useNavigate } from "react-router-dom";

import { NFDataTable, NFPagination, NFSearch, type Column } from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFEmptyState,
  NFPageHeader,
  NFSelect,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { api, type Page } from "@/services/api";
import type { Society, SocietyStatus } from "@/types";
import { formatDate, formatNumber } from "@/utils/format";

const STATUSES: SocietyStatus[] = [
  "ACTIVE",
  "PROVISIONING",
  "PROVISIONING_FAILED",
  "LOCKED",
  "SUSPENDED",
  "ARCHIVED",
];

export default function SocietyListPage() {
  const navigate = useNavigate();
  const [data, setData] = React.useState<Page<Society> | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [status, setStatus] = React.useState<string>("");

  // Debounced so typing does not issue a request per keystroke.
  const [debouncedQ, setDebouncedQ] = React.useState("");
  React.useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQ(q);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api
      .get<Page<Society>>(
        "/platform/societies",
        { page, limit: 25, q: debouncedQ, status, include_archived: status === "ARCHIVED" },
        controller.signal,
      )
      .then(setData)
      .catch((e) => {
        if ((e as Error).name !== "AbortError") setData(null);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, debouncedQ, status]);

  const columns: Column<Society>[] = [
    {
      key: "name",
      header: "Society",
      render: (s) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--nf-text)]">{s.name}</p>
          <p className="truncate text-xs text-[var(--nf-text-muted)]">{s.slug}</p>
        </div>
      ),
    },
    {
      key: "location",
      header: "Location",
      hideOnMobile: true,
      render: (s) => (
        <span className="text-[var(--nf-text-muted)]">
          {s.city}, {s.state}
        </span>
      ),
    },
    { key: "status", header: "Status", render: (s) => <NFStatusBadge status={s.status} /> },
    {
      key: "flats",
      header: "Flats",
      hideOnMobile: true,
      className: "tabular-nums",
      render: (s) => formatNumber(s.total_flats),
    },
    {
      key: "created",
      header: "Added",
      hideOnMobile: true,
      render: (s) => (
        <span className="text-[var(--nf-text-muted)]">{formatDate(s.created_at)}</span>
      ),
    },
  ];

  return (
    <>
      <NFPageHeader
        title="Societies"
        description="Every society on the platform. Each has its own isolated database."
        actions={
          <NFButton asChild>
            <Link to="/admin/societies/new">
              <Plus /> New society
            </Link>
          </NFButton>
        }
      />

      <NFCard>
        <div className="flex flex-wrap items-center gap-3 border-b border-[var(--nf-border)] p-4">
          <NFSearch value={q} onChange={setQ} placeholder="Search by name, city or slug…" />
          <NFSelect
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
            aria-label="Filter by status"
            className="sm:w-48"
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ")}
              </option>
            ))}
          </NFSelect>
        </div>

        <NFDataTable
          caption="Societies on the NestFlow platform"
          columns={columns}
          rows={data?.items ?? []}
          rowKey={(s) => s.id}
          loading={loading}
          onRowClick={(s) => navigate(`/admin/societies/${s.id}`)}
          empty={
            <NFEmptyState
              icon={<Building2 />}
              title={q || status ? "No matching societies" : "No societies yet"}
              description={
                q || status
                  ? "Try a different search term or clear the status filter."
                  : "Create the first society — its database is provisioned automatically."
              }
              action={
                !q && !status ? (
                  <NFButton asChild>
                    <Link to="/admin/societies/new">
                      <Plus /> Create a society
                    </Link>
                  </NFButton>
                ) : undefined
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
    </>
  );
}

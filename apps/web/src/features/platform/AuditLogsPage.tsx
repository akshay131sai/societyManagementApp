import { ScrollText } from "lucide-react";
import * as React from "react";

import { NFDataTable, NFDialog, NFPagination, type Column } from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFEmptyState,
  NFInput,
  NFPageHeader,
  NFSelect,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { ApiError, api, type Page } from "@/services/api";
import type { AuditLog, Society } from "@/types";
import { formatDateTime, formatRelative } from "@/utils/format";

/** `society.lock` reads better in a table than `SOCIETY_LOCK`. */
function humanAction(action: string): string {
  return action.replace(/[._]/g, " ").toLowerCase();
}

export default function AuditLogsPage() {
  const [data, setData] = React.useState<Page<AuditLog> | null>(null);
  const [societies, setSocieties] = React.useState<Society[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const [page, setPage] = React.useState(1);
  const [societyId, setSocietyId] = React.useState("");
  const [action, setAction] = React.useState("");
  const [debouncedAction, setDebouncedAction] = React.useState("");
  const [selected, setSelected] = React.useState<AuditLog | null>(null);

  React.useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedAction(action);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [action]);

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
      .get<Page<AuditLog>>(
        "/platform/audit-logs",
        { page, limit: 25, society_id: societyId, action: debouncedAction },
        controller.signal,
      )
      .then((p) => {
        setData(p);
        setError(null);
      })
      .catch((e) => {
        if ((e as Error).name === "AbortError") return;
        setError(e instanceof ApiError ? e.message : "Could not load the audit log.");
        setData(null);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, societyId, debouncedAction]);

  const societyName = React.useCallback(
    (id: string | null) => societies.find((s) => s.id === id)?.name ?? null,
    [societies],
  );

  const columns: Column<AuditLog>[] = [
    {
      key: "action",
      header: "Action",
      render: (l) => (
        <div className="min-w-0">
          <p className="truncate font-medium capitalize text-[var(--nf-text)]">
            {humanAction(l.action)}
          </p>
          {l.target_type && (
            <p className="truncate text-xs text-[var(--nf-text-muted)]">
              {l.target_type}
              {l.target_id ? ` · ${l.target_id.slice(0, 8)}` : ""}
            </p>
          )}
        </div>
      ),
    },
    {
      key: "actor",
      header: "Actor",
      render: (l) => (
        <span className="text-[13px] text-[var(--nf-text-muted)]">{l.actor_email ?? "System"}</span>
      ),
    },
    {
      key: "society",
      header: "Society",
      hideOnMobile: true,
      render: (l) => (
        <span className="text-[13px] text-[var(--nf-text-muted)]">
          {societyName(l.society_id) ?? (l.society_id ? "Unknown" : "Platform")}
        </span>
      ),
    },
    {
      key: "status",
      header: "Result",
      render: (l) => (
        <NFStatusBadge
          status={l.status}
          tone={l.status === "SUCCESS" ? "success" : l.status === "FAILURE" ? "danger" : undefined}
        />
      ),
    },
    {
      key: "when",
      header: "When",
      render: (l) => (
        <span className="text-[var(--nf-text-muted)]" title={formatDateTime(l.created_at)}>
          {formatRelative(l.created_at)}
        </span>
      ),
    },
  ];

  return (
    <>
      <NFPageHeader
        title="Audit Logs"
        description="Every privileged platform action, in order, with the actor who performed it. Append-only — entries are never edited or removed."
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
          <NFInput
            value={action}
            onChange={(e) => setAction(e.target.value)}
            placeholder="Filter by action, e.g. society.lock"
            aria-label="Filter by action"
            className="sm:w-64"
          />
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
          caption="Platform audit log"
          columns={columns}
          rows={data?.items ?? []}
          rowKey={(l) => String(l.id)}
          loading={loading}
          onRowClick={setSelected}
          empty={
            <NFEmptyState
              icon={<ScrollText />}
              title={action || societyId ? "No matching entries" : "No audit entries yet"}
              description={
                action || societyId
                  ? "Try a different action prefix or clear the society filter."
                  : "Privileged actions such as locking a society or assigning a subscription are recorded here."
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

      <NFDialog
        open={selected !== null}
        onOpenChange={(o) => !o && setSelected(null)}
        title={selected ? humanAction(selected.action) : ""}
        description={selected ? formatDateTime(selected.created_at) : undefined}
        size="lg"
        footer={
          <NFButton variant="secondary" onClick={() => setSelected(null)}>
            Close
          </NFButton>
        }
      >
        {selected && (
          <dl className="grid gap-x-6 gap-y-3 text-[13px] sm:grid-cols-2">
            <div>
              <dt className="text-[var(--nf-text-muted)]">Actor</dt>
              <dd className="mt-0.5 font-medium text-[var(--nf-text)]">
                {selected.actor_email ?? "System"}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--nf-text-muted)]">Result</dt>
              <dd className="mt-0.5">
                <NFStatusBadge
                  status={selected.status}
                  tone={
                    selected.status === "SUCCESS"
                      ? "success"
                      : selected.status === "FAILURE"
                        ? "danger"
                        : undefined
                  }
                />
              </dd>
            </div>
            <div>
              <dt className="text-[var(--nf-text-muted)]">Society</dt>
              <dd className="mt-0.5 text-[var(--nf-text)]">
                {societyName(selected.society_id) ?? (selected.society_id ? "Unknown" : "Platform")}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--nf-text-muted)]">Target</dt>
              <dd className="mt-0.5 text-[var(--nf-text)]">
                {selected.target_type ?? "—"}
                {selected.target_id && (
                  <span className="ml-1 font-mono text-xs text-[var(--nf-text-muted)]">
                    {selected.target_id}
                  </span>
                )}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-[var(--nf-text-muted)]">Request id</dt>
              <dd className="mt-0.5 font-mono text-xs text-[var(--nf-text)]">
                {selected.request_id ?? "—"}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-[var(--nf-text-muted)]">Changes</dt>
              <dd className="mt-1">
                {selected.changes && Object.keys(selected.changes).length > 0 ? (
                  <pre className="nf-scroll max-h-64 overflow-auto rounded-[var(--nf-radius-sm)] border border-[var(--nf-border)] bg-[var(--nf-background)] p-3 font-mono text-xs text-[var(--nf-text)]">
                    {JSON.stringify(selected.changes, null, 2)}
                  </pre>
                ) : (
                  <span className="text-[var(--nf-text-subtle)]">
                    No field-level changes recorded.
                  </span>
                )}
              </dd>
            </div>
          </dl>
        )}
      </NFDialog>
    </>
  );
}

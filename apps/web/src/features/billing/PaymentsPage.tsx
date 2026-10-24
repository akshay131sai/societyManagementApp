/**
 * Payments received.
 *
 * The recording of a payment lives on the bill it settles — that is where an
 * admin is when the money arrives. This screen is the ledger: what came in,
 * from which flat, by which method.
 *
 * A resident sees only their own payments, because the backend scopes the list
 * to their flats; nothing here filters by hand.
 */

import { IndianRupee, Wallet } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";

import { NFDataTable, NFPagination, NFSearch, NFStatCard, type Column } from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFEmptyState,
  NFPageHeader,
  NFSelect,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { api, type Page } from "@/services/api";
import { useAppSelector } from "@/store";
import type { PaymentMethod, PaymentRecord } from "@/types";
import { formatCurrency, formatDate } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

const METHODS: PaymentMethod[] = [
  "UPI",
  "NEFT",
  "CASH",
  "CHEQUE",
  "CARD",
  "NETBANKING",
  "ADJUSTMENT",
];

const LIMIT = 25;

export default function PaymentsPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const canSeeAll = hasPermission(principal, "billing.read_all");

  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [method, setMethod] = React.useState("");
  const [payments, setPayments] = React.useState<Page<PaymentRecord> | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api
      .get<Page<PaymentRecord>>("/payments", { page, limit: LIMIT }, controller.signal)
      .then(setPayments)
      .catch(() => undefined)
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page]);

  // Filtering happens client-side over the current page: the endpoint paginates
  // and a resident's ledger is short. An admin filtering a long history is
  // better served by the bill list, which filters server-side.
  const rows = (payments?.items ?? []).filter((p) => {
    if (method && p.method !== method) return false;
    if (!q.trim()) return true;
    const needle = q.trim().toLowerCase();
    return (
      (p.bill_number ?? "").toLowerCase().includes(needle) ||
      (p.reference_number ?? "").toLowerCase().includes(needle)
    );
  });

  const total = rows.reduce((sum, p) => sum + Number(p.amount), 0);

  const columns: Column<PaymentRecord>[] = [
    {
      key: "date",
      header: "Received",
      render: (p) => (
        <span className="whitespace-nowrap font-medium text-[var(--nf-text)]">
          {formatDate(p.paid_at ?? p.created_at)}
        </span>
      ),
    },
    {
      key: "bill",
      header: "Bill",
      render: (p) =>
        p.bill_number ? (
          <span className="font-mono text-[12px]">{p.bill_number}</span>
        ) : (
          <span className="text-[var(--nf-text-subtle)]">On account</span>
        ),
    },
    { key: "method", header: "Method", render: (p) => p.method },
    {
      key: "reference",
      header: "Reference",
      hideOnMobile: true,
      render: (p) => p.reference_number ?? "—",
    },
    {
      key: "status",
      header: "Status",
      hideOnMobile: true,
      render: (p) => <NFStatusBadge status={p.status} />,
    },
    {
      key: "amount",
      header: "Amount",
      className: "text-right tabular-nums font-semibold",
      headerClassName: "text-right",
      render: (p) => formatCurrency(p.amount),
    },
  ];

  return (
    <>
      <NFPageHeader
        title="Payments"
        description={
          canSeeAll
            ? "Every payment received against a maintenance bill."
            : "The payments recorded against your flat."
        }
        actions={
          <NFButton variant="secondary" asChild>
            <Link to="/app/bills">Go to bills</Link>
          </NFButton>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2">
        <NFStatCard
          label="Payments listed"
          value={payments?.total ?? 0}
          icon={<Wallet />}
          loading={loading}
        />
        <NFStatCard
          label="Total on this page"
          value={formatCurrency(total)}
          icon={<IndianRupee />}
          tone="success"
          loading={loading}
        />
      </div>

      <NFCard className="mt-6">
        <NFCardHeader
          title="Ledger"
          description="Newest first."
          action={
            <div className="flex flex-wrap items-center gap-2">
              <NFSelect
                aria-label="Filter by method"
                value={method}
                onChange={(e) => setMethod(e.target.value)}
                className="w-36"
              >
                <option value="">All methods</option>
                {METHODS.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </NFSelect>
              <NFSearch value={q} onChange={setQ} placeholder="Bill or reference" />
            </div>
          }
        />
        <NFCardBody className="px-0 pb-0">
          <NFDataTable
            caption="Payments"
            columns={columns}
            rows={rows}
            rowKey={(p) => p.id}
            loading={loading}
            empty={
              <div className="px-5 pb-5">
                <NFEmptyState
                  title={q || method ? "No matching payments" : "No payments yet"}
                  description={
                    q || method
                      ? "Try a different reference or method."
                      : "Payments recorded against a bill will appear here."
                  }
                />
              </div>
            }
          />
          {payments && payments.total > 0 && (
            <div className="px-5 py-4">
              <NFPagination
                page={payments.page}
                pages={payments.pages}
                total={payments.total}
                limit={payments.limit}
                onPageChange={setPage}
              />
            </div>
          )}
        </NFCardBody>
      </NFCard>
    </>
  );
}

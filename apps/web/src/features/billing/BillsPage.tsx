import {
  AlertTriangle,
  CheckCircle2,
  IndianRupee,
  ReceiptIndianRupee,
  Send,
  Wallet,
} from "lucide-react";
import * as React from "react";
import { useSearchParams } from "react-router-dom";

import {
  NFConfirmDialog,
  NFDataTable,
  NFDialog,
  NFPagination,
  NFSearch,
  NFStatCard,
  type Column,
} from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFCardBody,
  NFEmptyState,
  NFField,
  NFInput,
  NFPageHeader,
  NFSelect,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { BillDetailDialog } from "@/features/billing/BillDetailDialog";
import { ApiError, api, type Page } from "@/services/api";
import { useAppSelector } from "@/store";
import type { Bill, BillingRun, BillingSummary } from "@/types";
import { formatCurrency, formatDate } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

export default function BillsPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const canPublish = hasPermission(principal, "billing.publish");
  const canSeeAll = hasPermission(principal, "billing.read_all");
  const canPay = hasPermission(principal, "payment.record");

  const [search, setSearch] = useSearchParams();
  const runId = search.get("run_id") ?? "";

  const [data, setData] = React.useState<Page<Bill> | null>(null);
  const [summary, setSummary] = React.useState<BillingSummary | null>(null);
  const [run, setRun] = React.useState<BillingRun | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [paymentStatus, setPaymentStatus] = React.useState("");
  const [refreshKey, setRefreshKey] = React.useState(0);

  const [viewing, setViewing] = React.useState<string | null>(null);
  const [paying, setPaying] = React.useState<Bill | null>(null);
  const [publishing, setPublishing] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const [debouncedQ, setDebouncedQ] = React.useState("");
  React.useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQ(q);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  const refresh = React.useCallback(() => setRefreshKey((k) => k + 1), []);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    Promise.all([
      api.get<Page<Bill>>(
        "/billing/bills",
        { page, limit: 25, q: debouncedQ, run_id: runId, payment_status: paymentStatus },
        controller.signal,
      ),
      canSeeAll
        ? api.get<BillingSummary>("/billing/summary", undefined, controller.signal)
        : Promise.resolve(null),
      runId ? api.get<BillingRun>(`/billing/runs/${runId}`, undefined, controller.signal) : Promise.resolve(null),
    ])
      .then(([bills, s, r]) => {
        setData(bills);
        setSummary(s);
        setRun(r);
      })
      .catch((e) => {
        if ((e as Error).name !== "AbortError") setData(null);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, debouncedQ, runId, paymentStatus, refreshKey, canSeeAll]);

  async function publish() {
    if (!run) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/billing/runs/${run.id}/publish`);
      setPublishing(false);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not publish this run.");
      setPublishing(false);
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<Bill>[] = [
    {
      key: "bill",
      header: "Bill",
      render: (b) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--nf-text)]">{b.flat_number}</p>
          <p className="truncate font-mono text-[11px] text-[var(--nf-text-muted)]">
            {b.bill_number}
          </p>
        </div>
      ),
    },
    {
      key: "period",
      header: "Period",
      hideOnMobile: true,
      render: (b) => <span className="text-[var(--nf-text-muted)]">{b.period_label}</span>,
    },
    {
      key: "total",
      header: "Amount",
      className: "tabular-nums font-medium",
      render: (b) => formatCurrency(b.total, true),
    },
    {
      key: "due",
      header: "Due",
      hideOnMobile: true,
      render: (b) => <span className="text-[var(--nf-text-muted)]">{formatDate(b.due_date)}</span>,
    },
    {
      key: "status",
      header: "Status",
      render: (b) =>
        b.status === "DRAFT" || b.status === "VOID" || b.status === "FAILED" ? (
          <NFStatusBadge status={b.status} />
        ) : (
          <NFStatusBadge status={b.payment_status} />
        ),
    },
    ...(canPay
      ? [
          {
            key: "actions",
            header: "",
            headerClassName: "w-24",
            render: (b: Bill) =>
              b.status === "PUBLISHED" && b.payment_status !== "PAID" ? (
                <NFButton
                  variant="secondary"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    setPaying(b);
                  }}
                >
                  <Wallet /> Pay
                </NFButton>
              ) : null,
          },
        ]
      : []),
  ];

  const draftRun = run && run.status !== "PUBLISHED";

  return (
    <>
      <NFPageHeader
        title="Bills"
        description={
          canSeeAll
            ? "Maintenance bills for every flat, by period."
            : "Your maintenance bills."
        }
        actions={
          draftRun && canPublish ? (
            <NFButton onClick={() => setPublishing(true)}>
              <Send /> Publish {run.bills_generated} bill(s)
            </NFButton>
          ) : undefined
        }
      />

      {error && (
        <div
          role="alert"
          className="mb-5 rounded-[var(--nf-radius)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] p-3.5 text-sm text-[var(--nf-text)]"
        >
          {error}
        </div>
      )}

      {run && (
        <NFCard className="mb-5">
          <NFCardBody className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="flex items-center gap-2 text-sm font-medium text-[var(--nf-text)]">
                {run.template_name} · {run.period_label}
                <NFStatusBadge status={run.status} />
              </p>
              <p className="mt-0.5 text-[13px] text-[var(--nf-text-muted)]">
                {run.bills_generated} bill(s) · {formatCurrency(run.total_amount)} · due{" "}
                {formatDate(run.due_date)}
                {run.bills_failed > 0 && (
                  <span className="ml-2 text-[var(--nf-danger)]">
                    {run.bills_failed} failed
                  </span>
                )}
              </p>
            </div>
            <NFButton
              variant="ghost"
              size="sm"
              onClick={() => {
                search.delete("run_id");
                setSearch(search);
              }}
            >
              Show all bills
            </NFButton>
          </NFCardBody>
        </NFCard>
      )}

      {run?.error_summary && run.error_summary.length > 0 && (
        <NFCard className="mb-5 border-[var(--nf-danger)]/30">
          <NFCardBody>
            <p className="flex items-center gap-1.5 text-[13px] font-semibold text-[var(--nf-danger)]">
              <AlertTriangle className="size-3.5" aria-hidden />
              {run.error_summary.length} flat(s) could not be billed
            </p>
            <ul className="mt-2 space-y-1 text-[12px] text-[var(--nf-text-muted)]">
              {run.error_summary.slice(0, 5).map((e, i) => (
                <li key={i}>
                  <span className="font-medium text-[var(--nf-text)]">{e.flat_number}</span> —{" "}
                  {e.message}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[12px] text-[var(--nf-text-subtle)]">
              The other bills generated normally. Fix these and run the period again.
            </p>
          </NFCardBody>
        </NFCard>
      )}

      {summary && summary.total_bills > 0 && (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <NFStatCard
            label="Billed"
            value={formatCurrency(summary.total_billed)}
            hint={`${summary.total_bills} published bill(s)`}
            icon={<ReceiptIndianRupee />}
          />
          <NFStatCard
            label="Collected"
            value={formatCurrency(summary.total_collected)}
            hint={`${summary.collection_rate}% of billed`}
            icon={<CheckCircle2 />}
            tone="success"
          />
          <NFStatCard
            label="Outstanding"
            value={formatCurrency(summary.total_outstanding)}
            icon={<IndianRupee />}
            tone={Number(summary.total_outstanding) > 0 ? "warning" : "success"}
          />
          <NFStatCard
            label="Unpaid bills"
            value={
              (summary.by_payment_status.UNPAID ?? 0) +
              (summary.by_payment_status.PARTIAL ?? 0) +
              (summary.by_payment_status.OVERDUE ?? 0)
            }
            icon={<Wallet />}
            tone="info"
          />
        </div>
      )}

      <NFCard>
        <div className="flex flex-wrap items-center gap-3 border-b border-[var(--nf-border)] p-4">
          <NFSearch value={q} onChange={setQ} placeholder="Search bill number…" />
          <NFSelect
            value={paymentStatus}
            onChange={(e) => {
              setPaymentStatus(e.target.value);
              setPage(1);
            }}
            aria-label="Filter by payment status"
            className="sm:w-44"
          >
            <option value="">All statuses</option>
            <option value="UNPAID">Unpaid</option>
            <option value="PARTIAL">Partly paid</option>
            <option value="PAID">Paid</option>
            <option value="OVERDUE">Overdue</option>
          </NFSelect>
        </div>

        <NFDataTable
          caption="Maintenance bills"
          columns={columns}
          rows={data?.items ?? []}
          rowKey={(b) => b.id}
          loading={loading}
          onRowClick={(b) => setViewing(b.id)}
          empty={
            <NFEmptyState
              icon={<ReceiptIndianRupee />}
              title={q || paymentStatus ? "No matching bills" : "No bills yet"}
              description={
                q || paymentStatus
                  ? "Try a different search term or clear the filters."
                  : canSeeAll
                    ? "Build a bill template, then generate a billing run."
                    : "Your maintenance bills will appear here once the society publishes them."
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

      <BillDetailDialog billId={viewing} onClose={() => setViewing(null)} />

      <PaymentDialog
        bill={paying}
        onClose={() => setPaying(null)}
        onRecorded={() => {
          setPaying(null);
          refresh();
        }}
      />

      <NFConfirmDialog
        open={publishing}
        onOpenChange={setPublishing}
        title={`Publish ${run?.bills_generated ?? 0} bill(s)?`}
        description="Published bills become immutable and visible to residents. A wrong bill is then corrected with a credit note, never an edit."
        confirmLabel="Publish"
        loading={busy}
        onConfirm={publish}
      />
    </>
  );
}

/* -------------------------------------------------------------------------- */

function PaymentDialog({
  bill,
  onClose,
  onRecorded,
}: {
  bill: Bill | null;
  onClose: () => void;
  onRecorded: () => void;
}) {
  const [amount, setAmount] = React.useState("");
  const [method, setMethod] = React.useState("UPI");
  const [reference, setReference] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (bill) {
      setAmount(bill.balance_due);
      setMethod("UPI");
      setReference("");
      setError(null);
    }
  }, [bill]);

  async function record() {
    if (!bill) return;
    setBusy(true);
    setError(null);
    try {
      await api.post("/payments", {
        bill_id: bill.id,
        amount,
        method,
        reference_number: reference || null,
      });
      onRecorded();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not record this payment.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <NFDialog
      open={bill !== null}
      onOpenChange={(o) => !o && onClose()}
      title="Record a payment"
      description={bill ? `${bill.bill_number} · Flat ${bill.flat_number}` : undefined}
      size="sm"
      footer={
        <>
          <NFButton variant="secondary" onClick={onClose}>
            Cancel
          </NFButton>
          <NFButton onClick={record} loading={busy}>
            Record payment
          </NFButton>
        </>
      }
    >
      <div className="space-y-4">
        {error && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
          >
            {error}
          </p>
        )}

        {bill && (
          <dl className="space-y-1.5 rounded-[var(--nf-radius)] bg-[var(--nf-background)] p-3 text-[13px]">
            <div className="flex justify-between">
              <dt className="text-[var(--nf-text-muted)]">Bill total</dt>
              <dd className="tabular-nums text-[var(--nf-text)]">
                {formatCurrency(bill.total, true)}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-[var(--nf-text-muted)]">Already paid</dt>
              <dd className="tabular-nums text-[var(--nf-text)]">
                {formatCurrency(bill.amount_paid, true)}
              </dd>
            </div>
            <div className="flex justify-between font-medium">
              <dt className="text-[var(--nf-text)]">Balance due</dt>
              <dd className="tabular-nums text-[var(--nf-primary)]">
                {formatCurrency(bill.balance_due, true)}
              </dd>
            </div>
          </dl>
        )}

        <NFField label="Amount" htmlFor="pay-amount" required>
          <NFInput
            id="pay-amount"
            type="number"
            step="0.01"
            min="0.01"
            max={bill?.balance_due}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </NFField>

        <NFField label="Method" htmlFor="pay-method" required>
          <NFSelect id="pay-method" value={method} onChange={(e) => setMethod(e.target.value)}>
            {["UPI", "NEFT", "CASH", "CHEQUE", "CARD", "NETBANKING", "ADJUSTMENT"].map((m) => (
              <option key={m} value={m}>
                {m === "ADJUSTMENT" ? "Adjustment" : m}
              </option>
            ))}
          </NFSelect>
        </NFField>

        <NFField label="Reference" htmlFor="pay-ref" hint="UTR, cheque number, receipt number">
          <NFInput
            id="pay-ref"
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            placeholder="Optional"
          />
        </NFField>
      </div>
    </NFDialog>
  );
}

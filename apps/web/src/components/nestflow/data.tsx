/**
 * Data display components: stat cards, tables, pagination, dialogs, toasts.
 *
 * `NFDataTable` renders a semantic `<table>` with a caption and scoped
 * headers, inside its own horizontal-scroll container so the page body never
 * scrolls sideways on mobile.
 */

import * as Dialog from "@radix-ui/react-dialog";
import { ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import * as React from "react";

import { NFButton, NFCard, NFEmptyState, NFInput, NFSkeleton } from "@/components/nestflow/primitives";
import { cn } from "@/utils/cn";

/* -------------------------------------------------------------------------- */
/* Stat card                                                                  */
/* -------------------------------------------------------------------------- */

export function NFStatCard({
  label,
  value,
  icon,
  hint,
  trend,
  tone = "primary",
  loading,
  className,
}: {
  label: string;
  value: React.ReactNode;
  icon?: React.ReactNode;
  hint?: string;
  trend?: { value: number; label?: string };
  tone?: "primary" | "success" | "warning" | "danger" | "info";
  loading?: boolean;
  className?: string;
}) {
  const toneVar = {
    primary: "--nf-primary",
    success: "--nf-success",
    warning: "--nf-warning",
    danger: "--nf-danger",
    info: "--nf-info",
  }[tone];

  return (
    <NFCard className={cn("p-5", className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[13px] font-medium text-[var(--nf-text-muted)]">{label}</p>
          {loading ? (
            <NFSkeleton className="mt-2 h-8 w-20" />
          ) : (
            <p className="mt-1.5 text-2xl font-semibold tracking-tight text-[var(--nf-text)]">
              {value}
            </p>
          )}
          {hint && !loading && (
            <p className="mt-1 truncate text-xs text-[var(--nf-text-subtle)]">{hint}</p>
          )}
          {trend && !loading && (
            <p
              className="mt-1.5 text-xs font-medium"
              style={{
                color: trend.value >= 0 ? "var(--nf-success)" : "var(--nf-danger)",
              }}
            >
              {trend.value >= 0 ? "↑" : "↓"} {Math.abs(trend.value)}%
              {trend.label && (
                <span className="ml-1 font-normal text-[var(--nf-text-subtle)]">{trend.label}</span>
              )}
            </p>
          )}
        </div>
        {icon && (
          <span
            className="flex size-10 shrink-0 items-center justify-center rounded-[var(--nf-radius-sm)] [&_svg]:size-5"
            style={{
              backgroundColor: `color-mix(in oklab, var(${toneVar}) 12%, transparent)`,
              color: `var(${toneVar})`,
            }}
            aria-hidden
          >
            {icon}
          </span>
        )}
      </div>
    </NFCard>
  );
}

/* -------------------------------------------------------------------------- */
/* Data table                                                                 */
/* -------------------------------------------------------------------------- */

export interface Column<T> {
  key: string;
  header: string;
  /** Cell renderer. Keep it pure — this runs for every visible row. */
  render: (row: T) => React.ReactNode;
  className?: string;
  headerClassName?: string;
  /** Hidden below `sm`, so a mobile table shows only what matters. */
  hideOnMobile?: boolean;
}

export interface NFDataTableProps<T> {
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  skeletonRows?: number;
  empty?: React.ReactNode;
  onRowClick?: (row: T) => void;
  className?: string;
}

export function NFDataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  loading,
  skeletonRows = 5,
  empty,
  onRowClick,
  className,
}: NFDataTableProps<T>) {
  if (!loading && rows.length === 0) {
    return (
      <div className={className}>
        {empty ?? <NFEmptyState title="Nothing to show yet" description="No records were found." />}
      </div>
    );
  }

  return (
    // Wide content scrolls inside its own container; the page never does.
    <div className={cn("nf-scroll w-full overflow-x-auto", className)}>
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-[var(--nf-border)]">
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={cn(
                  "px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-[var(--nf-text-muted)]",
                  col.hideOnMobile && "hidden sm:table-cell",
                  col.headerClassName,
                )}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading
            ? Array.from({ length: skeletonRows }).map((_, i) => (
                <tr key={i} className="border-b border-[var(--nf-border)]">
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={cn("px-4 py-3.5", col.hideOnMobile && "hidden sm:table-cell")}
                    >
                      <NFSkeleton className="h-4 w-full max-w-28" />
                    </td>
                  ))}
                </tr>
              ))
            : rows.map((row) => (
                <tr
                  key={rowKey(row)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  tabIndex={onRowClick ? 0 : undefined}
                  role={onRowClick ? "button" : undefined}
                  onKeyDown={
                    onRowClick
                      ? (e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            onRowClick(row);
                          }
                        }
                      : undefined
                  }
                  className={cn(
                    "border-b border-[var(--nf-border)] transition-colors last:border-0",
                    onRowClick &&
                      "cursor-pointer hover:bg-[var(--nf-primary-subtle)] focus-visible:bg-[var(--nf-primary-subtle)]",
                  )}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={cn(
                        "px-4 py-3.5 text-[var(--nf-text)]",
                        col.hideOnMobile && "hidden sm:table-cell",
                        col.className,
                      )}
                    >
                      {col.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
        </tbody>
      </table>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Pagination — server-side only. The client never holds a full dataset.      */
/* -------------------------------------------------------------------------- */

export function NFPagination({
  page,
  pages,
  total,
  limit,
  onPageChange,
  className,
}: {
  page: number;
  pages: number;
  total: number;
  limit: number;
  onPageChange: (page: number) => void;
  className?: string;
}) {
  if (total === 0) return null;

  const from = (page - 1) * limit + 1;
  const to = Math.min(page * limit, total);

  return (
    <nav
      aria-label="Pagination"
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 border-t border-[var(--nf-border)] px-4 py-3",
        className,
      )}
    >
      <p className="text-[13px] text-[var(--nf-text-muted)]">
        Showing <span className="font-medium text-[var(--nf-text)]">{from}</span>–
        <span className="font-medium text-[var(--nf-text)]">{to}</span> of{" "}
        <span className="font-medium text-[var(--nf-text)]">{total}</span>
      </p>
      <div className="flex items-center gap-2">
        <NFButton
          variant="secondary"
          size="sm"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          aria-label="Previous page"
        >
          <ChevronLeft /> Previous
        </NFButton>
        <span className="px-1 text-[13px] text-[var(--nf-text-muted)]" aria-current="page">
          {page} / {Math.max(pages, 1)}
        </span>
        <NFButton
          variant="secondary"
          size="sm"
          disabled={page >= pages}
          onClick={() => onPageChange(page + 1)}
          aria-label="Next page"
        >
          Next <ChevronRight />
        </NFButton>
      </div>
    </nav>
  );
}

/* -------------------------------------------------------------------------- */
/* Search input                                                               */
/* -------------------------------------------------------------------------- */

export function NFSearch({
  value,
  onChange,
  placeholder = "Search…",
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <NFInput
      type="search"
      role="searchbox"
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      leadingIcon={<Search />}
      className={cn("sm:w-64", className)}
      aria-label={placeholder}
    />
  );
}

/* -------------------------------------------------------------------------- */
/* Dialog — Radix supplies focus trapping, escape and aria wiring             */
/* -------------------------------------------------------------------------- */

export function NFDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: "sm" | "md" | "lg";
}) {
  const width = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl" }[size];

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/45 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0" />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2",
            "rounded-[var(--nf-radius-lg)] border border-[var(--nf-border)] bg-[var(--nf-surface)] nf-shadow-lg",
            "max-h-[calc(100vh-3rem)] overflow-y-auto nf-scroll",
            "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95",
            width,
          )}
        >
          <div className="flex items-start justify-between gap-4 border-b border-[var(--nf-border)] px-5 py-4">
            <div className="min-w-0">
              <Dialog.Title className="text-base font-semibold text-[var(--nf-text)]">
                {title}
              </Dialog.Title>
              {description && (
                <Dialog.Description className="mt-1 text-[13px] text-[var(--nf-text-muted)]">
                  {description}
                </Dialog.Description>
              )}
            </div>
            <Dialog.Close asChild>
              <NFButton variant="ghost" size="icon-sm" aria-label="Close">
                <X />
              </NFButton>
            </Dialog.Close>
          </div>

          <div className="px-5 py-4">{children}</div>

          {footer && (
            <div className="flex flex-wrap justify-end gap-2 border-t border-[var(--nf-border)] px-5 py-4">
              {footer}
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function NFConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive,
  loading,
  onConfirm,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  children?: React.ReactNode;
}) {
  return (
    <NFDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
          <NFButton variant="secondary" onClick={() => onOpenChange(false)} disabled={loading}>
            {cancelLabel}
          </NFButton>
          <NFButton
            variant={destructive ? "danger" : "primary"}
            onClick={onConfirm}
            loading={loading}
          >
            {confirmLabel}
          </NFButton>
        </>
      }
    >
      {children ?? (
        <p className="text-sm text-[var(--nf-text-muted)]">
          This action cannot be undone automatically.
        </p>
      )}
    </NFDialog>
  );
}
